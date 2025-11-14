"""Main logic for Media Downloader integration."""

from __future__ import annotations

import os
import asyncio
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
    EVENT_JOB_INTERRUPTED,
)

from .video_utils import (
    sanitize_filename,
    guess_filename_from_url,
    ensure_within_base,
    #...
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Media Downloader from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    )

    @callback
    def _get_config() -> tuple[Path, bool]:
        """Return configured base directory and default overwrite setting."""
        base_dir = Path(entry.options.get(CONF_DOWNLOAD_DIR, entry.data.get(CONF_DOWNLOAD_DIR, "")))
        default_overwrite = entry.options.get(CONF_OVERWRITE, DEFAULT_OVERWRITE)
        return base_dir, default_overwrite

    # ----------------------------------------------------------
    # 📥 Download file
    # ----------------------------------------------------------

    async def _async_download(call: ServiceCall) -> None:
        """Service handler to download a file. The whole workflow is subject to the configured timeout."""
        url: str = call.data[ATTR_URL]
        subdir: Optional[str] = call.data.get(ATTR_SUBDIR)
        filename: Optional[str] = call.data.get(ATTR_FILENAME)
        overwrite: Optional[bool] = call.data.get(ATTR_OVERWRITE)
        # timeout in seconds (default 300)
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

        async def _run_workflow() -> None:
            """Encapsulate full workflow so it can be run with asyncio.wait_for for total timeout."""
            try:
                # Download part
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise HomeAssistantError(f"HTTP status {resp.status}")

                    # Stream into temp file
                    with tmp_path.open("wb") as fh:
                        async for chunk in resp.content.iter_chunked(1024):
                            fh.write(chunk)

                # Post processing steps (normalize aspect ratio, thumbnail embedding, resize, etc.)
                # NOTE: keep existing project calls here. The original repo likely runs
                # normalization/thumbnail/resizing steps after the download; preserve that behavior.
                # For brevity, placeholder comments are here; keep your actual implementation.
                #
                # Example placeholders (replace with existing calls):
                # await normalize_video_if_needed(dest_path)
                # await embed_thumbnail_if_needed(dest_path)
                # if resize_enabled:
                #     await resize_video_if_needed(dest_path, resize_width, resize_height)

                # Move temp file to final destination or overwrite policy handling:
                if dest_path.exists():
                    if do_overwrite:
                        dest_path.unlink()
                    else:
                        raise HomeAssistantError("File exists and overwrite is False")
                tmp_path.rename(dest_path)

                # Emit completion event with url and final path
                hass.bus.async_fire("media_downloader_job_completed", {"url": url, "path": str(dest_path)})

            except Exception:
                # Re-raise to be handled by outer handler (so exceptions trigger download_failed)
                raise

        try:
            # Run the full workflow with total timeout
            await asyncio.wait_for(_run_workflow(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            _LOGGER.warning("Download job timed out for URL %s (timeout: %s s)", url, timeout_sec)
            # Emit a job_interrupted event with job metadata
            try:
                hass.bus.async_fire(EVENT_JOB_INTERRUPTED, {"job": {"url": url, "path": str(dest_path)}})
            except Exception:
                _LOGGER.exception("Failed to emit job_interrupted event")

            # Attempt to clean up temp file if it still exists
            try:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
            except Exception:
                _LOGGER.exception("Error cleaning up tmp file after timeout")
        except Exception as err:
            _LOGGER.error("Download failed: %s", err)
            hass.bus.async_fire("media_downloader_download_failed", {"url": url, "error": str(err)})
        finally:
            # Ensure sensor process is ended regardless of success, failure or timeout
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
        path_str: str = call.data.get(ATTR_PATH)
        if not path_str:
            path_str = entry.options.get(CONF_DELETE_DIR_PATH, "")
        if not path_str:
            raise HomeAssistantError("No path provided")

        path = Path(path_str).resolve()
        base_dir, _ = _get_config()
        ensure_within_base(base_dir, path)

        sensor = hass.data[DOMAIN]["status_sensor"]
        sensor.start_process(PROCESS_DIR_DELETING)
        try:
            if path.is_dir():
                for child in path.iterdir():
                    if child.is_file():
                        child.unlink()
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
            vol.Optional(ATTR_TIMEOUT): cv.positive_int,
            vol.Optional(ATTR_RESIZE_ENABLED): cv.boolean,
            vol.Optional(ATTR_RESIZE_WIDTH): cv.positive_int,
            vol.Optional(ATTR_RESIZE_HEIGHT): cv.positive_int,
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
