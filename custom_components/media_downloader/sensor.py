from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


class MediaDownloaderStatusSensor(SensorEntity):
    """Sensor to track Media Downloader status."""

    _attr_name = "Media Downloader Status"
    _attr_unique_id = "media_downloader_status"

    def __init__(self, hass: HomeAssistant) -> None:
        self._attr_native_value: str = "idle"
        self._attr_extra_state_attributes: dict[str, Any] = {
            "last_changed": None,
            "subprocess": None,
            "active_processes": [],
        }
        self._hass = hass
        self._active_processes: set[str] = set()

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        self._attr_extra_state_attributes["last_changed"] = datetime.now().isoformat()

    def start_process(self, name: str) -> None:
        """Mark a subprocess as started."""
        self._active_processes.add(name)
        self._attr_native_value = "working"
        self._attr_extra_state_attributes["subprocess"] = name
        self._attr_extra_state_attributes["active_processes"] = list(self._active_processes)
        self._attr_extra_state_attributes["last_changed"] = datetime.now().isoformat()
        self.async_write_ha_state()

    def end_process(self, name: str) -> None:
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
        """Return device info for grouping in HA UI."""
        return DeviceInfo(
            identifiers={(DOMAIN, "media_downloader_status")},
            name="Media Downloader",
            manufacturer="Geek-MD",
        )
