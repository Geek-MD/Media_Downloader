from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

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
    ATTR_RESIZED,
    PROCESS_DOWNLOADING,
    PROCESS_RESIZING,
    PROCESS_FILE_DELETING,
    PROCESS_DIR_DELETING,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up Media Downloader integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Media Downloader from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    directory = Path(entry.data[CONF_DOWNLOAD_DIR])
    overwrite = entry.data.get(CONF_OVERWRITE, DEFAULT_OVERWRITE)
    default_file_delete_path = entry.data.get(CONF_DELETE_FILE_PATH)
    default_dir_delete_path = entry.data.get(CONF_DELETE_DIR_PATH)

    directory.mkdir(parents=True, exist_ok=True)

    hass.data[DOMAIN].update(
        {
            "directory": directory,
            "overwrite": overwrite,
            "default_file_delete_path": default_file_delete_path,
            "default_dir_delete_path": default_dir_delete_path,
        }
    )

    # Ensure status sensor is initialized
    if "status_sensor" not in hass.data[DOMAIN]:
        from .sensor import MediaDownloaderStatusSensor

        sensor = MediaDownloaderStatusSensor(hass)
        hass.data[DOMAIN]["status_sensor"] = sensor

        async def _register_sensor() -> None:
            """Register the sensor in Home Assistant if not already added."""
            await hass.helpers.entity_component.async_add_entities([sensor])  # type: ignore

        hass.async_create_task(_register_sensor())

    async def handle_download_file(call: ServiceCall) -> None:
        """Handle downloading a file."""
        url: str = call.data[ATTR_URL]
        subdir: str | None = call.data.get(ATTR_SUBDIR)
        filename: str | None = call.data.get(ATTR_FILENAME)
        overwrite_opt: bool = call.data.get(ATTR_OVERWRITE, overwrite)
        timeout_sec: int = call.data.get(ATTR_TIMEOUT, 300)

        resize_enabled: bool = call.data.get(ATTR_RESIZE_ENABLED, False)
        resize_width: int = call.data.get(ATTR_RESIZE_WIDTH, 640)
        resize_height: int = call.data.get(ATTR_RESIZE_HEIGHT, 360)

        dest_path = directory / (subdir or "")
        dest_path.mkdir(parents=True, exist_ok=True)

        if not filename:
            filename = os.path.basename(url.split("?")[0])

        file_path = dest_path / filename

        if file_path.exists() and not overwrite_opt:
            _LOGGER.warning("File %s exists and overwrite disabled", file_path)
            return

        sensor = hass.data[DOMAIN].get("status_sensor")
        if sensor:
            sensor.start_process(PROCESS_DOWNLOADING)

        try:
            proc = await asyncio.create_subprocess_exec(
                "curl",
                "-L",
                "-o",
                str(file_path),
                url,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
            except asyncio.TimeoutError:
                proc.kill()
                raise

            resized = False
            if resize_enabled and file_path.exists():
                # Verificar dimensiones con ffprobe
                try:
                    probe = subprocess.run(
                        [
                            "ffprobe",
                            "-v",
                            "error",
                            "-select_streams",
                            "v:0",
                            "-show_entries",
                            "stream=width,height",
                            "-of",
                            "json",
                            str(file_path),
                        ],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    import json

                    data: dict[str, Any] = json.loads(probe.stdout)
                    width = data["streams"][0]["width"]
                    height = data["streams"][0]["height"]

                    if width != resize_width or height != resize_height:
                        resized_path = file_path.with_suffix(".resized" + file_path.suffix)
                        cmd = [
                            "ffmpeg",
                            "-i",
                            str(file_path),
                            "-vf",
                            f"scale={resize_width}:{resize_height},setsar=1,setdar={resize_width}/{resize_height}",
                            "-c:a",
                            "copy",
                            str(resized_path),
                        ]
                        subprocess.run(cmd, check=True)
                        shutil.move(str(resized_path), str(file_path))
                        resized = True
                except Exception as e:
                    _LOGGER.error("Resize failed for %s: %s", file_path, e)

            hass.bus.async_fire(
                "media_downloader_job_completed",
                {
                    "url": url,
                    "path": str(file_path),
                    ATTR_RESIZED: resized,
                },
            )
        finally:
            if sensor:
                sensor.end_process(PROCESS_DOWNLOADING)

    async def handle_delete_file(call: ServiceCall) -> None:
        """Handle deleting a single file."""
        path = call.data.get("path") or default_file_delete_path
        if not path:
            _LOGGER.error("No file path provided for deletion")
            return

        sensor = hass.data[DOMAIN].get("status_sensor")
        if sensor:
            sensor.start_process(PROCESS_FILE_DELETING)

        try:
            os.remove(path)
            hass.bus.async_fire(
                "media_downloader_delete_completed", {"path": path, "success": True}
            )
        except Exception as e:
            hass.bus.async_fire(
                "media_downloader_delete_completed",
                {"path": path, "success": False, "error": str(e)},
            )
        finally:
            if sensor:
                sensor.end_process(PROCESS_FILE_DELETING)

    async def handle_delete_directory(call: ServiceCall) -> None:
        """Handle deleting all files in a directory."""
        path = call.data.get("path") or default_dir_delete_path
        if not path:
            _LOGGER.error("No directory path provided for deletion")
            return

        sensor = hass.data[DOMAIN].get("status_sensor")
        if sensor:
            sensor.start_process(PROCESS_DIR_DELETING)

        try:
            for file in Path(path).glob("*"):
                if file.is_file():
                    os.remove(file)
            hass.bus.async_fire(
                "media_downloader_delete_directory_completed",
                {"path": path, "success": True},
            )
        except Exception as e:
            hass.bus.async_fire(
                "media_downloader_delete_directory_completed",
                {"path": path, "success": False, "error": str(e)},
            )
        finally:
            if sensor:
                sensor.end_process(PROCESS_DIR_DELETING)

    hass.services.async_register(DOMAIN, SERVICE_DOWNLOAD_FILE, handle_download_file)
    hass.services.async_register(DOMAIN, SERVICE_DELETE_FILE, handle_delete_file)
    hass.services.async_register(DOMAIN, SERVICE_DELETE_DIRECTORY, handle_delete_directory)

    return True
