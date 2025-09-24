"""Media Downloader integration for Home Assistant."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import json
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    CONF_DOWNLOAD_DIR,
    CONF_OVERWRITE,
    CONF_DELETE_FILE_PATH,
    CONF_DELETE_DIR_PATH,
    DEFAULT_OVERWRITE,
    DEFAULT_TIMEOUT,
    SERVICE_DOWNLOAD_FILE,
    SERVICE_DELETE_FILE,
    SERVICE_DELETE_FILES_IN_DIRECTORY,
    PROCESS_DOWNLOADING,
    PROCESS_RESIZING,
    PROCESS_FILE_DELETING,
    PROCESS_DIR_DELETING,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Media Downloader integration (YAML not supported)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Media Downloader from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    directory = Path(entry.data[CONF_DOWNLOAD_DIR])
    overwrite = entry.data.get(CONF_OVERWRITE, DEFAULT_OVERWRITE)
    default_file_delete_path = entry.data.get(CONF_DELETE_FILE_PATH)
    default_dir_delete_path = entry.data.get(CONF_DELETE_DIR_PATH)

    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)

    # Recuperamos el sensor desde hass.data (lo crea sensor.py)
    sensor = hass.data[DOMAIN].get("status_sensor")
    if sensor is None:
        _LOGGER.error("Media Downloader status sensor is not initialized")
        return False

    async def _async_download(call: ServiceCall) -> None:
        """Handle download_file service."""
        url = call.data["url"]
        subdir = call.data.get("subdir")
        filename = call.data.get("filename")
        overwrite_flag = call.data.get("overwrite", overwrite)
        timeout_sec = call.data.get("timeout", DEFAULT_TIMEOUT)
        resize_enabled = call.data.get("resize_enabled", False)
        resize_width = call.data.get("resize_width", 640)
        resize_height = call.data.get("resize_height", 360)

        dest_dir = directory / subdir if subdir else directory
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest_path = dest_dir / (filename or os.path.basename(url))

        if dest_path.exists() and not overwrite_flag:
            _LOGGER.warning("File %s already exists and overwrite is disabled", dest_path)
            return

        tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")

        sensor.start_process(PROCESS_DOWNLOADING)

        try:
            proc = await asyncio.create_subprocess_exec(
                "wget",
                "-O",
                str(tmp_path),
                url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                hass.bus.async_fire(
                    "media_downloader_download_failed",
                    {"url": url, "error": "Download timeout"},
                )
                return

            if proc.returncode != 0:
                stderr = (await proc.communicate())[1].decode()
                hass.bus.async_fire(
                    "media_downloader_download_failed",
                    {"url": url, "error": stderr},
                )
                return

            shutil.move(str(tmp_path), str(dest_path))
            hass.bus.async_fire(
                "media_downloader_download_completed",
                {"url": url, "path": str(dest_path), "resized": resize_enabled},
            )

            if resize_enabled:
                sensor.start_process(PROCESS_RESIZING)
                success = await hass.async_add_executor_job(
                    _resize_video, dest_path, resize_width, resize_height
                )
                if success:
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
                        {"url": url, "path": str(dest_path), "resized": True},
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
                sensor.end_process(PROCESS_RESIZING)
            else:
                hass.bus.async_fire(
                    "media_downloader_job_completed",
                    {"url": url, "path": str(dest_path), "resized": False},
                )

        finally:
            sensor.end_process(PROCESS_DOWNLOADING)

    async def _async_delete_file(call: ServiceCall) -> None:
        """Handle delete_file service."""
        path = Path(call.data.get("path") or default_file_delete_path)
        if not path:
            _LOGGER.warning("No path provided for delete_file")
            return

        sensor.start_process(PROCESS_FILE_DELETING)
        try:
            if path.exists() and path.is_file():
                path.unlink()
                hass.bus.async_fire(
                    "media_downloader_delete_completed",
                    {"path": str(path), "success": True},
                )
            else:
                hass.bus.async_fire(
                    "media_downloader_delete_completed",
                    {"path": str(path), "success": False, "error": "File not found"},
                )
        finally:
            sensor.end_process(PROCESS_FILE_DELETING)

    async def _async_delete_files_in_directory(call: ServiceCall) -> None:
        """Handle delete_files_in_directory service."""
        dir_path = Path(call.data.get("path") or default_dir_delete_path)
        if not dir_path:
            _LOGGER.warning("No path provided for delete_files_in_directory")
            return

        sensor.start_process(PROCESS_DIR_DELETING)
        try:
            if dir_path.exists() and dir_path.is_dir():
                for f in dir_path.iterdir():
                    if f.is_file():
                        f.unlink()
                hass.bus.async_fire(
                    "media_downloader_delete_directory_completed",
                    {"path": str(dir_path), "success": True},
                )
            else:
                hass.bus.async_fire(
                    "media_downloader_delete_directory_completed",
                    {"path": str(dir_path), "success": False, "error": "Directory not found"},
                )
        finally:
            sensor.end_process(PROCESS_DIR_DELETING)

    hass.services.async_register(DOMAIN, SERVICE_DOWNLOAD_FILE, _async_download)
    hass.services.async_register(DOMAIN, SERVICE_DELETE_FILE, _async_delete_file)
    hass.services.async_register(DOMAIN, SERVICE_DELETE_FILES_IN_DIRECTORY, _async_delete_files_in_directory)

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True


def _get_video_dimensions(path: Path) -> tuple[int, int]:
    """Detect video dimensions robustly using ffprobe JSON with ffmpeg fallback."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json", str(path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if streams:
            width = int(streams[0].get("width", 0))
            height = int(streams[0].get("height", 0))
            if width > 0 and height > 0:
                return width, height
    except Exception as err:
        _LOGGER.warning("ffprobe failed for %s: %s", path, err)

    # fallback with ffmpeg -i
    try:
        cmd = ["ffmpeg", "-i", str(path)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        match = re.search(r",\s*(\d{2,5})x(\d{2,5})", result.stderr)
        if match:
            return int(match.group(1)), int(match.group(2))
    except Exception as err:
        _LOGGER.warning("ffmpeg fallback failed for %s: %s", path, err)

    return (0, 0)


def _resize_video(path: Path, width: int, height: int) -> bool:
    """Resize video to fixed dimensions and normalize SAR/DAR."""
    try:
        tmp_path = path.with_suffix(".resized" + path.suffix)
        cmd = [
            "ffmpeg", "-y", "-i", str(path),
            "-vf", f"scale={width}:{height},setsar=1,setdar={width}/{height}",
            "-c:v", "libx264", "-preset", "veryfast",
            "-c:a", "copy",
            str(tmp_path)
        ]
        subprocess.run(cmd, check=True)

        shutil.move(str(tmp_path), str(path))
        return True
    except Exception as err:
        _LOGGER.error("Resize failed for %s: %s", path, err)
        return False
