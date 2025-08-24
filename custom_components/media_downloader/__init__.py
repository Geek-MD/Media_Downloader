from __future__ import annotations

import os
import re
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
    EVENT_DOWNLOAD_STARTED,
    EVENT_DOWNLOAD_COMPLETED,
    EVENT_DELETE_COMPLETED,
    EVENT_DELETE_DIRECTORY_COMPLETED,
)

PLATFORMS: list = []  # No entities yet, only services


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    @callback
    def _get_config() -> tuple[Path, bool]:
        download_dir = Path(
            entry.options.get(CONF_DOWNLOAD_DIR, entry.data.get(CONF_DOWNLOAD_DIR))
        )
        overwrite = bool(
            entry.options.get(CONF_OVERWRITE, entry.data.get(CONF_OVERWRITE, DEFAULT_OVERWRITE))
        )
        return (download_dir, overwrite)

    def _log_and_fire(event_type: str, success: bool, path: str, error: str | None) -> None:
        hass.bus.async_fire(
            event_type,
            {"path": path, "success": success, "error": error},
        )

    # --------------------- Servicio principal: descargar archivo ---------------------

    async def _async_download(call: ServiceCall) -> None:
        url: str = call.data[ATTR_URL]
        subdir: Optional[str] = call.data.get(ATTR_SUBDIR)
        filename: Optional[str] = call.data.get(ATTR_FILENAME)
        overwrite: Optional[bool] = call.data.get(ATTR_OVERWRITE)
        timeout_sec: int = int(call.data.get(ATTR_TIMEOUT, 300))

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

        hass.bus.async_fire(
            EVENT_DOWNLOAD_STARTED,
            {
                "url": url,
                "path": str(dest_path),
                "overwrite": do_overwrite,
            },
        )

        session: aiohttp.ClientSession = aiohttp_client.async_get_clientsession(hass)
        tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")

        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

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

            hass.bus.async_fire(
                EVENT_DOWNLOAD_COMPLETED,
                {
                    "url": url,
                    "path": str(dest_path),
                    "success": True,
                    "error": None,
                },
            )

        except Exception as e:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass

            hass.bus.async_fire(
                EVENT_DOWNLOAD_COMPLETED,
                {
                    "url": url,
                    "path": str(dest_path),
                    "success": False,
                    "error": str(e),
                },
            )
            raise

    # --------------------- Servicio: eliminar un archivo ---------------------

    async def _async_delete_file(call: ServiceCall) -> None:
        path_str: str = call.data[ATTR_PATH]
        path = Path(path_str).resolve()
        base_dir, _ = _get_config()

        _ensure_within_base(base_dir, path)

        try:
            if path.is_file():
                path.unlink()
                _log_and_fire(EVENT_DELETE_COMPLETED, True, str(path), None)
            else:
                raise HomeAssistantError(f"Not a file: {path}")
        except Exception as e:
            _log_and_fire(EVENT_DELETE_COMPLETED, False, str(path), str(e))

    # --------------------- Servicio: eliminar todos los archivos de un directorio ---------------------

    async def _async_delete_directory(call: ServiceCall) -> None:
        dir_str: str = call.data[ATTR_PATH]
        dir_path = Path(dir_str).resolve()
        base_dir, _ = _get_config()

        _ensure_within_base(base_dir, dir_path)

        if not dir_path.is_dir():
            _log_and_fire(EVENT_DELETE_DIRECTORY_COMPLETED, False, str(dir_path), "Not a directory")
            return

        errors = []
        for child in dir_path.iterdir():
            try:
                if child.is_file():
                    child.unlink()
            except Exception as e:
                errors.append(f"{child}: {e}")

        success = not errors
        _log_and_fire(EVENT_DELETE_DIRECTORY_COMPLETED, success, str(dir_path), "\n".join(errors) if errors else None)

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
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_FILE,
        _async_delete_file,
        schema=vol.Schema({vol.Required(ATTR_PATH): cv.string}),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_DIRECTORY,
        _async_delete_directory,
        schema=vol.Schema({vol.Required(ATTR_PATH): cv.string}),
    )

    async def _options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
        await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.services.async_remove(DOMAIN, SERVICE_DOWNLOAD_FILE)
    hass.services.async_remove(DOMAIN, SERVICE_DELETE_FILE)
    hass.services.async_remove(DOMAIN, SERVICE_DELETE_DIRECTORY)
    return True
