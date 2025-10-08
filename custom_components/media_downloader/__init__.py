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
PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Media Downloader from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    @callback
    def _get_config() -> tuple[Path, bool]:
        """Retrieve configured base directory and overwrite policy."""
        download_dir = Path(entry.options.get(CONF_DOWNLOAD_DIR, entry.data.get(CONF_DOWNLOAD_DIR)))
        overwrite = bool(entry.options.get(CONF_OVERWRITE, entry.data.get(CONF_OVERWRITE, DEFAULT_OVERWRITE)))
        return (download_dir, overwrite)

    # --------------------- Service: Download file --------------------- #

    async def _async_download(call: ServiceCall) -> None:
        """Download a file, optionally resize and fix aspect for Telegram."""
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

        # Determine final destination directory
        if subdir:
            dest_dir = (base_dir / sanitize_filename(subdir)).resolve()
        else:
            dest_dir = base_dir
        ensure_within_base(base_dir, dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Build the final destination path
        final_name = sanitize_filename(filename) if filename else guess_filename_from_url(url)
        dest_path = (dest_dir / final_name).resolve()
        ensure_within_base(base_dir, dest_path)

        do_overwrite = default_overwrite if overwrite_arg is None else bool(overwrite_arg)

        # Start download session
        session: aiohttp.ClientSession = aiohttp_client.async_get_clientsession(hass)
        tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

        try:
            async with async_timeout.timeout(timeout_sec):
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise HomeAssistantError(f"HTTP error {resp.status} for {url}")

                    # Try to extract filename from Content-Disposition
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
                        raise HomeAssistantError(f"File exists and overwrite=false: {dest_path}")

                    # Stream file content to disk
                    with open(tmp_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(65536):
                            f.write(chunk)

            if dest_path.exists() and do_overwrite:
                tmp_path.replace(dest_path)
            else:
                tmp_path.rename(dest_path)

            # Video postprocessing
            if dest_path.suffix.lower() in (".mp4", ".mov", ".mkv", ".avi"):
                if resize_enabled:
                    optional_resize_video(dest_path, resize_width, resize_height)

                # Always fix Telegram preview/aspect ratio
                fix_telegram_aspect(dest_path)

            _LOGGER.info("Downloaded successfully: %s", dest_path)

        except Exception as err:
            _LOGGER.error("Download failed for %s: %s", url, err)
            raise

    # --------------------- Service: Delete file --------------------- #

    async def _async_delete_file(call: ServiceCall) -> None:
        """Delete a specific file within the base directory."""
        path_str: str = call.data.get(ATTR_PATH)
        if not path_str:
            path_str = entry.options.get(CONF_DELETE_FILE_PATH, "")
        if not path_str:
            raise HomeAssistantError("No path provided for delete_file")

        base_dir, _ = _get_config()
        file_path = Path(path_str).resolve()
        ensure_within_base(base_dir, file_path)

        if file_path.is_file():
            file_path.unlink()
            _LOGGER.info("Deleted file: %s", file_path)
        else:
            raise HomeAssistantError(f"Not a file: {file_path}")

    # --------------------- Service: Delete directory --------------------- #

    async def _async_delete_directory(call: ServiceCall) -> None:
        """Delete all files in a given directory."""
        dir_str: str = call.data.get(ATTR_PATH)
        if not dir_str:
            dir_str = entry.options.get(CONF_DELETE_DIR_PATH, "")
        if not dir_str:
            raise HomeAssistantError("No path provided for delete_files_in_directory")

        base_dir, _ = _get_config()
        dir_path = Path(dir_str).resolve()
        ensure_within_base(base_dir, dir_path)

        if not dir_path.is_dir():
            raise HomeAssistantError(f"Not a directory: {dir_path}")

        for child in dir_path.iterdir():
            if child.is_file():
                child.unlink(missing_ok=True)
        _LOGGER.info("Cleared directory: %s", dir_path)

    # --------------------- Register services --------------------- #

    hass.services.async_register(
        DOMAIN,
        SERVICE_DOWNLOAD_FILE,
        _async_download,
        schema=vol.Schema({
            vol.Required(ATTR_URL): cv.url,
            vol.Optional(ATTR_SUBDIR): cv.string,
            vol.Optional(ATTR_FILENAME): cv.string,
            vol.Optional(ATTR_OVERWRITE): cv.boolean,
            vol.Optional(ATTR_TIMEOUT): vol.Coerce(int),
            vol.Optional(ATTR_RESIZE_ENABLED): cv.boolean,
            vol.Optional(ATTR_RESIZE_WIDTH): vol.Coerce(int),
            vol.Optional(ATTR_RESIZE_HEIGHT): vol.Coerce(int),
        }),
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

    # ✅ Restore sensor platform setup
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Media Downloader config entry."""
    hass.services.async_remove(DOMAIN, SERVICE_DOWNLOAD_FILE)
    hass.services.async_remove(DOMAIN, SERVICE_DELETE_FILE)
    hass.services.async_remove(DOMAIN, SERVICE_DELETE_DIRECTORY)
    await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    return True
