from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import aiohttp_client, config_validation as cv

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
)

from .video_tools import (
    sanitize_filename,
    ensure_within_base,
    guess_filename_from_url,
    optional_resize_video,
    fix_telegram_aspect,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["sensor"]  # keep platform list if you use the status sensor


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Media Downloader from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    @callback
    def _get_config() -> tuple[Path, bool]:
        download_dir = Path(entry.options.get(CONF_DOWNLOAD_DIR, entry.data.get(CONF_DOWNLOAD_DIR)))
        overwrite = bool(entry.options.get(CONF_OVERWRITE, entry.data.get(CONF_OVERWRITE, DEFAULT_OVERWRITE)))
        return (download_dir, overwrite)

    # --------------------- Service: download file --------------------- #

    async def _async_download(call: ServiceCall) -> None:
        url: str = call.data[ATTR_URL]
        subdir: Optional[str] = call.data.get(ATTR_SUBDIR)
        filename: Optional[str] = call.data.get(ATTR_FILENAME)
        overwrite_arg: Optional[bool] = call.data.get(ATTR_OVERWRITE)
        timeout_sec: int = int(call.data.get(ATTR_TIMEOUT, 300))

        resize_enabled: bool = call.data.get(ATTR_RESIZE_ENABLED, False)
        resize_width: int = int(call.data.get(ATTR_RESIZE_WIDTH, 640))
        resize_height: int = int(call.data.get(ATTR_RESIZE_HEIGHT, 360))

        base_dir, default_overwrite = _get_config()
        base_dir = base_dir.resolve()

        # Build destination dir: base or base/subdir (never above base)
        if subdir:
            dest_dir = (base_dir / sanitize_filename(subdir)).resolve()
        else:
            dest_dir = base_dir
        ensure_within_base(base_dir, dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Build final path
        final_name = sanitize_filename(filename) if filename else guess_filename_from_url(url)
        dest_path = (dest_dir / final_name).resolve()
        ensure_within_base(base_dir, dest_path)

        do_overwrite = default_overwrite if overwrite_arg is None else bool(overwrite_arg)

        # Stream download to temp file
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

                    # Content-Disposition filename override (best-effort)
                    if not filename:
                        cd = resp.headers.get("Content-Disposition") or resp.headers.get("content-disposition")
                        if cd:
                            import re as _re
                            m = _re.search(r'filename\*=.*?\'\'([^;]+)|filename="?([^";]+)"?', cd)
                            if m:
                                candidate = m.group(1) or m.group(2)
                                if candidate:
                                    final_name_cd = sanitize_filename(candidate)
                                    dest_path = (dest_dir / final_name_cd).resolve()
                                    ensure_within_base(base_dir, dest_path)
                                    tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")

                    if dest_path.exists() and not do_overwrite:
                        raise HomeAssistantError(f"File already exists and overwrite=false: {dest_path}")

                    with open(tmp_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(1024 * 64):
                            if chunk:
                                f.write(chunk)

            # Move into place
            if dest_path.exists() and do_overwrite:
                tmp_path.replace(dest_path)
            else:
                tmp_path.rename(dest_path)

            # Optional resize (only if video, detected by common extensions)
            if dest_path.suffix.lower() in (".mp4", ".mov", ".mkv", ".avi"):
                if resize_enabled:
                    optional_resize_video(dest_path, resize_width, resize_height)
                # Telegram fix ALWAYS
                fix_telegram_aspect(dest_path)

            _LOGGER.info("Media Downloader: completed %s", dest_path)

        except Exception as err:
            _LOGGER.error("Media Downloader: download failed for %s: %s", url, err)
            raise

    # --------------------- Service: delete file --------------------- #

    async def _async_delete_file(call: ServiceCall) -> None:
        path_str: str = call.data.get(ATTR_PATH)
        if not path_str:
            path_str = entry.options.get(CONF_DELETE_FILE_PATH, "")
        if not path_str:
            raise HomeAssistantError("No path provided for delete_file")

        base_dir, _ = _get_config()
        file_path = Path(path_str).resolve()
        ensure_within_base(base_dir.resolve(), file_path)

        if file_path.is_file():
            file_path.unlink()
            _LOGGER.info("Media Downloader: deleted file %s", file_path)
        else:
            raise HomeAssistantError(f"Not a file: {file_path}")

    # ------------- Service: delete all files in directory ----------- #

    async def _async_delete_directory(call: ServiceCall) -> None:
        dir_str: str = call.data.get(ATTR_PATH)
        if not dir_str:
            dir_str = entry.options.get(CONF_DELETE_DIR_PATH, "")
        if not dir_str:
            raise HomeAssistantError("No path provided for delete_files_in_directory")

        base_dir, _ = _get_config()
        dir_path = Path(dir_str).resolve()
        ensure_within_base(base_dir.resolve(), dir_path)

        if not dir_path.is_dir():
            raise HomeAssistantError(f"Not a directory: {dir_path}")

        for child in dir_path.iterdir():
            try:
                if child.is_file():
                    child.unlink()
            except Exception:
                # continue best-effort
                pass
        _LOGGER.info("Media Downloader: cleared directory %s", dir_path)

    # --------------------- Register services --------------------- #

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

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Media Downloader config entry."""
    hass.services.async_remove(DOMAIN, SERVICE_DOWNLOAD_FILE)
    hass.services.async_remove(DOMAIN, SERVICE_DELETE_FILE)
    hass.services.async_remove(DOMAIN, SERVICE_DELETE_DIRECTORY)
    return True
