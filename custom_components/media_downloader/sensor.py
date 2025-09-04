from __future__ import annotations

from datetime import datetime
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


class MediaDownloaderStatusSensor(SensorEntity):
    """Sensor to track Media Downloader status."""

    def __init__(self, hass):
        self._attr_name = "Media Downloader Status"
        self._attr_unique_id = "media_downloader_status"
        self._attr_native_value = "idle"
        self._attr_extra_state_attributes = {
            "last_changed": None,
            "subprocess": None,
            "active_processes": [],
        }
        self._hass = hass
        self._active_processes: set[str] = set()

    async def async_added_to_hass(self):
        self._attr_extra_state_attributes["last_changed"] = datetime.now().isoformat()

    def start_process(self, name: str):
        """Mark a subprocess as started."""
        self._active_processes.add(name)
        self._attr_native_value = "working"
        self._attr_extra_state_attributes["subprocess"] = name
        self._attr_extra_state_attributes["active_processes"] = list(self._active_processes)
        self._attr_extra_state_attributes["last_changed"] = datetime.now().isoformat()
        self.async_write_ha_state()

    def end_process(self, name: str):
        """Mark a subprocess as finished."""
        self._active_processes.discard(name)
        if not self._active_processes:
            self._attr_native_value = "idle"
            self._attr_extra_state_attributes["subprocess"] = None
        else:
            self._attr_extra_state_attributes["subprocess"] = next(iter(self._active_processes))
        self._attr_extra_state_attributes["active_processes"] = list(self._active_processes)
        self._attr_extra_state_attributes["last_changed"] = datetime.now().isoformat()
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "media_downloader_status")},
            name="Media Downloader",
            manufacturer="Geek-MD",
        )
