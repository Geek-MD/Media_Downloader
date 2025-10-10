"""Main logic for Media Downloader integration."""

from __future__ import annotations

import os
import re
import async_timeout
import aiohttp
import logging
from pathlib import Path
from typing import Optional

import voluptuous as vol
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

from .video_utils import (
    sanitize_filename,
    guess_filename_from_url,
    ensure_within_base,
    normalize_video_aspect,
    embed_thumbnail,
    resize_video,
    get_video_dimensions,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Media Downloader from a config entry."""
    hass.data.setdefault(DOMAIN, {})

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

    # ----------------------------------------------------------
    # 📥 Download file
    # ----------------------------------------------------------

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

        dest_dir = base_dir / sanitize_filename(subdir or "")
        ensure_within_base(base_dir, dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        final_name = sanitize_filename(filename) if filename else guess_filename_from_url(url)
        dest_path = (dest_dir / final_name).resolve()
        ensure_within_base(base_dir, dest_path)

        do_overwrite = default_overwrite if overwrite is None else bool(overwrite)

        sensor = hass.data[DOMAIN]["status_sensor"]
        sensor.start_process(PROCESS_DOWNLOADING)

        session: aiohttp.ClientSession = aiohttp_client.async_get_clientsession(hass)
        tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")

        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

        try:
            async with async_timeout.timeout(timeout_sec):
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise HomeAssistantError(f"HTTP error {resp.status}: {url}")
                    with open(tmp_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(1024 * 64):
                            if chunk:
                                f.write(chunk)

            if dest_path.exists() and not do_overwrite:
                raise HomeAssistantError(f"File exists and overwrite is False: {dest_path}")

            os.replace(tmp_path, dest_path)

            hass.bus.async_fire("media_downloader_download_completed", {
                "url": url, "path": str(dest_path)
            })

            # Always normalize aspect and embed thumbnail
            if normalize_video_aspect(dest_path):
                hass.bus.async_fire("media_downloader_aspect_normalized", {
                    "path": str(dest_path)
                })

            if embed_thumbnail(dest_path):
                hass.bus.async_fire("media_downloader_thumbnail_embedded", {
                    "path": str(dest_path)
                })

            # Optional resize
            if resize_enabled and dest_path.suffix.lower() in [".mp4", ".mov", ".mkv", ".avi"]:
                w, h = get_video_dimensions(dest_path)
                if w != resize_width or h != resize_height:
                    sensor.start_process(PROCESS_RESIZING)
                    if resize_video(dest_path, resize_width, resize_height):
                        hass.bus.async_fire("media_downloader_resize_completed", {
                            "path": str(dest_path), "width": resize_width, "height": resize_height
                        })
                    else:
                        hass.bus.async_fire("media_downloader_resize_failed", {
                            "path": str(dest_path)
                        })
                    sensor.end_process(PROCESS_RESIZING)

            hass.bus.async_fire("media_downloader_job_completed", {
                "url": url, "path": str(dest_path)
            })

        except Exception as err:
            _LOGGER.error("Download failed: %s", err)
            hass.bus.async_fire("media_downloader_download_failed", {
                "url": url, "error": str(err)
            })
        finally:
            sensor.end_process(PROCESS_DOWNLOADING)

    # ----------------------------------------------------------
    # 🗑️ Delete file / directory
    # ----------------------------------------------------------

    async def _async_delete_file(call: ServiceCall) -> None:
        path_str: str = call.data.get(ATTR_PATH)
        if not path_str:
            path_str = entry.options.get(CONF_DELETE_FILE_PATH, "")
        if not path_str:
            raise HomeAssistantError("No path provided")

        path = Path(path_str).resolve()
        base_dir, _ = _get_config()
        ensure_within_base(base_dir, path)

        sensor = hass.data[DOMAIN]["status_sensor"]
        sensor.start_process(PROCESS_FILE_DELETING)
        try:
            if path.is_file():
                path.unlink()
        finally:
            sensor.end_process(PROCESS_FILE_DELETING)

    async def _async_delete_directory(call: ServiceCall) -> None:
        dir_str: str = call.data.get(ATTR_PATH)
        if not dir_str:
            dir_str = entry.options.get(CONF_DELETE_DIR_PATH, "")
        if not dir_str:
            raise HomeAssistantError("No path provided")

        dir_path = Path(dir_str).resolve()
        base_dir, _ = _get_config()
        ensure_within_base(base_dir, dir_path)

        sensor = hass.data[DOMAIN]["status_sensor"]
        sensor.start_process(PROCESS_DIR_DELETING)
        try:
            if dir_path.is_dir():
                for file in dir_path.iterdir():
                    if file.is_file():
                        file.unlink()
        finally:
            sensor.end_process(PROCESS_DIR_DELETING)

    # ----------------------------------------------------------
    # 🔧 Register services
    # ----------------------------------------------------------

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

    return True
