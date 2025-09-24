from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Optional

import aiohttp
import voluptuous as vol
import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import aiohttp_client, config_validation as cv
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    CONF_DOWNLOAD_DIR,
    CONF_OVERWRITE,
    CONF_DELETE_FILE_PATH,
    CONF_DELETE_DIR_PATH,
    DEFAULT_OVERWRITE,
    SERVICE_DOWNLOAD_FILE,
    SERVICE_DELETE_FILE,
    SERVICE_DELETE_DIRECTORY,
    ATTR_URL,
    ATTR_SUBDIR,
    ATTR_FILENAME,
    ATTR_OVERWRITE,
    ATTR_TIMEOUT,
    ATTR_PATH,
    ATTR_RESIZE_ENABLED,
    ATTR_RESIZE_WIDTH,
    ATTR_RESIZE_HEIGHT,
    PROCESS_DOWNLOADING,
    PROCESS_RESIZING,
    PROCESS_FILE_DELETING,
    PROCESS_DIR_DELETING,
)

PLATFORMS: list[str] = ["sensor"]


def _sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]", "_", name)
    return name or "downloaded_file"


def _ensure_within_base(base: Path, target: Path) -> None:
    try:
        target.relative_to(base)
    except Exception:
        raise HomeAssistantError(f"Path outside allowed base directory: {target}")


def _guess_filename_from_url(url: str) -> str:
    tail = url.split("?")[0].rstrip("/").split("/")[-1]
    return _sanitize_filename(tail or "downloaded_file")


def _get_video_dimensions(path: Path) -> tuple[int, int]:
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0", str(path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        width, height = map(int, result.stdout.strip().split("x"))
        return width, height
    except Exception:
        return (0, 0)


def _resize_video(path: Path, width: int, height: int) -> bool:
    tmp_resized = path.with_suffix(".resized" + path.suffix)
    cmd = [
        "ffmpeg", "-y", "-i", str(path),
        "-vf", f"scale={width}:{height}",
        "-c:a", "copy",
        str(tmp_resized)
    ]
    try:
        subprocess.run(cmd, check=True)
        os.replace(tmp_resized, path)
        return True
    except Exception:
        if tmp_resized.exists():
            tmp_resized.unlink()
        return False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Media Downloader from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Forward setup to sensor platform
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    )

    @callback
    def _get_config() -> tuple[Path, bool]:
        download_dir = Path(
            entry.options.get(CONF_DOWNLOAD_DIR, entry.data.get(CONF_DOWNLOAD_DIR))
        )
        overwrite = bool(
            entry.options.get(CONF_OVERWRITE, entry.data.get(CONF_OVERWRITE, DEFAULT_OVERWRITE))
        )
        return (download_dir, overwrite)

    # --------------------- Servicio principal: descargar archivo ---------------------

    async def _async_download(call: ServiceCall) -> None:
        url: str = call.data[ATTR_URL]
        subdir: Optional[str] = call.data.get(ATTR_SUBDIR)
        filename: Optional[str] = call.data.get(ATTR_FILENAME)
        overwrite: Optional[bool] = call.data.get(ATTR_OVERWRITE)
        timeout_sec: int = int(call.data.get(ATTR_TIMEOUT, 300))

        resize_enabled: bool = call.data.get(ATTR_RESIZE_ENABLED, False)
        resize_width: int = int(call.data.get(ATTR_RESIZE_WIDTH, 640))
        resize_height: int = int(call.data.get(ATTR_RESIZE_HEIGHT, 360))

        base_dir, default_overwrite = _get_config()
        base_dir = base_dir.resolve()

        if subdir:
            safe_subdir = Path(_sanitize_filename(subdir))
            dest_dir = (base_dir / safe_subdir).resolve()
        else:
            dest_dir = base_dir

        _ensure_within_base(base_dir, dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        final_name = _sanitize_filename(filename) if filename else _guess_filename_from_url(url)
        dest_path = (dest_dir / final_name).resolve()
        _ensure_within_base(base_dir, dest_path)

        do_overwrite = default_overwrite if overwrite is None else bool(overwrite)

        session: aiohttp.ClientSession = aiohttp_client.async_get_clientsession(hass)
        tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")

        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

        sensor = hass.data[DOMAIN]["status_sensor"]
        sensor.start_process(PROCESS_DOWNLOADING)

        try:
            async with async_timeout.timeout(timeout_sec):
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise HomeAssistantError(f"HTTP error {resp.status} while downloading: {url}")

                    if not filename:
                        cd = resp.headers.get("Content-Disposition") or resp.headers.get("content-disposition")
                        if cd:
                            m = re.search(r'filename\*=.*?\'\'([^;]+)|filename="?([^";]+)"?', cd)
                            if m:
                                candidate = m.group(1) or m.group(2)
                                if candidate:
                                    final_name_cd = _sanitize_filename(candidate)
                                    dest_path = (dest_dir / final_name_cd).resolve()
                                    _ensure_within_base(base_dir, dest_path)
                                    tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")

                    if dest_path.exists() and not do_overwrite:
                        raise HomeAssistantError(f"File already exists and overwrite=false: {dest_path}")

                    with open(tmp_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(1024 * 64):
                            if chunk:
                                f.write(chunk)

            if dest_path.exists() and do_overwrite:
                os.replace(tmp_path, dest_path)
            else:
                os.rename(tmp_path, dest_path)

            # Fire download completed event
            hass.bus.async_fire(
                "media_downloader_download_completed",
                {
                    "url": url,
                    "path": str(dest_path),
                    "resized": resize_enabled,
                },
            )

            # Si no hay resize -> job_completed aquí mismo
            if not resize_enabled:
                hass.bus.async_fire(
                    "media_downloader_job_completed",
                    {
                        "url": url,
                        "path": str(dest_path),
                        "resized": False,
                    },
                )

            if resize_enabled and dest_path.suffix.lower() in [".mp4", ".mov", ".mkv", ".avi"]:
                sensor.start_process(PROCESS_RESIZING)
                try:
                    w, h = _get_video_dimensions(dest_path)
                    if w != resize_width or h != resize_height:
                        if _resize_video(dest_path, resize_width, resize_height):
                            hass.bus.async_fire(
                                "media_downloader_resize_completed",
                                {
                                    "path": str(dest_path),
                                    "width": resize_width,
                                    "height": resize_height,
                                },
                            )
                            hass.bus.async_fire(
                                "media_downloader_job_completed",
                                {
                                    "url": url,
                                    "path": str(dest_path),
                                    "resized": True,
                                },
                            )
                        else:
                            hass.bus.async_fire(
                                "media_downloader_resize_failed",
                                {
                                    "path": str(dest_path),
                                    "width": resize_width,
                                    "height": resize_height,
                                },
                            )
                    else:
                        # Already correct size
                        hass.bus.async_fire(
                            "media_downloader_resize_completed",
                            {
                                "path": str(dest_path),
                                "width": resize_width,
                                "height": resize_height,
                            },
                        )
                        hass.bus.async_fire(
                            "media_downloader_job_completed",
                            {
                                "url": url,
                                "path": str(dest_path),
                                "resized": True,
                            },
                        )
                finally:
                    sensor.end_process(PROCESS_RESIZING)

        except Exception as err:
            hass.bus.async_fire(
                "media_downloader_download_failed",
                {
                    "url": url,
                    "error": str(err),
                },
            )
            raise
        finally:
            sensor.end_process(PROCESS_DOWNLOADING)

    # --------------------- Servicio: eliminar un archivo ---------------------

    async def _async_delete_file(call: ServiceCall) -> None:
        path_str: str = call.data.get(ATTR_PATH)
        if not path_str:
            path_str = entry.options.get(CONF_DELETE_FILE_PATH, "")
        if not path_str:
            raise HomeAssistantError("No path provided for delete_file")

        path = Path(path_str).resolve()
        base_dir, _ = _get_config()
        _ensure_within_base(base_dir, path)

        sensor = hass.data[DOMAIN]["status_sensor"]
        sensor.start_process(PROCESS_FILE_DELETING)
        try:
            if path.is_file():
                path.unlink()
            else:
                raise HomeAssistantError(f"Not a file: {path}")
        finally:
            sensor.end_process(PROCESS_FILE_DELETING)

    # --------------------- Servicio: eliminar todos los archivos de un directorio ---------------------

    async def _async_delete_directory(call: ServiceCall) -> None:
        dir_str: str = call.data.get(ATTR_PATH)
        if not dir_str:
            dir_str = entry.options.get(CONF_DELETE_DIR_PATH, "")
        if not dir_str:
            raise HomeAssistantError("No path provided for delete_files_in_directory")

        dir_path = Path(dir_str).resolve()
        base_dir, _ = _get_config()
        _ensure_within_base(base_dir, dir_path)

        sensor = hass.data[DOMAIN]["status_sensor"]
        sensor.start_process(PROCESS_DIR_DELETING)
        try:
            if not dir_path.is_dir():
                raise HomeAssistantError(f"Not a directory: {dir_path}")

            for child in dir_path.iterdir():
                try:
                    if child.is_file():
                        child.unlink()
                except Exception:
                    pass
        finally:
            sensor.end_process(PROCESS_DIR_DELETING)

    # --------------------- Registro de servicios ---------------------

    hass.services.async_register(
        DOMAIN,
        SERVICE_DOWNLOAD_FILE,
        _async_download,
        schema=vol.Schema(
            {
                vol.Required(ATTR_URL): cv.url,
                vol.Optional(ATTR_SUBDIR): cv.string,
                vol.Optional(ATTR_FILENAME): cv.string,
                vol.Optional(ATTR_OVERWRITE): cv.boolean,
                vol.Optional(ATTR_TIMEOUT): vol.Coerce(int),
                vol.Optional(ATTR_RESIZE_ENABLED): cv.boolean,
                vol.Optional(ATTR_RESIZE_WIDTH): vol.Coerce(int),
                vol.Optional(ATTR_RESIZE_HEIGHT): vol.Coerce(int),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_FILE,
        _async_delete_file,
        schema=vol.Schema({vol.Optional(ATTR_PATH): cv.string}),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_DIRECTORY,
        _async_delete_directory,
        schema=vol.Schema({vol.Optional(ATTR_PATH): cv.string}),
    )

    async def _options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
        await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Media Downloader config entry."""
    hass.services.async_remove(DOMAIN, SERVICE_DOWNLOAD_FILE)
    hass.services.async_remove(DOMAIN, SERVICE_DELETE_FILE)
    hass.services.async_remove(DOMAIN, SERVICE_DELETE_DIRECTORY)
    await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    return True
