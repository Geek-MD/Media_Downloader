from __future__ import annotations

from typing import Any, Callable
from datetime import datetime

from homeassistant.core import HomeAssistant, Event
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, EVENT_JOB_INTERRUPTED_NS, EVENT_JOB_INTERRUPTED


class MediaDownloaderStatusSensor(SensorEntity):
    """Sensor to track Media Downloader status and last job result."""

    _attr_name = "Media Downloader Status"
    _attr_unique_id = "media_downloader_status"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the sensor entity."""
        self._attr_native_value: str = "idle"
        # Add last_job attribute (None | "done" | "interrupted")
        self._attr_extra_state_attributes: dict[str, Any] = {
            "last_changed": None,
            "subprocess": None,
            "active_processes": [],
            "last_job": None,
        }
        self._hass = hass
        self._active_processes: set[str] = set()
        # List of unsubscribe callbacks returned by hass.bus.async_listen
        self._listeners: list[Callable[[], None]] = []

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to Home Assistant.

        Subscribe to job completed and job interrupted events to keep last_job updated.
        """
        self._attr_extra_state_attributes["last_changed"] = datetime.now().isoformat()

        # Subscribe to the integration events to update last_job attribute
        # media_downloader_job_completed -> last_job = "done"
        # job_interrupted and media_downloader_job_interrupted -> last_job = "interrupted"
        self._listeners.append(
            self._hass.bus.async_listen(
                "media_downloader_job_completed", self._handle_job_completed
            )
        )
        # listen to both interruption event names
        self._listeners.append(
            self._hass.bus.async_listen(EVENT_JOB_INTERRUPTED, self._handle_job_interrupted)
        )
        self._listeners.append(
            self._hass.bus.async_listen(EVENT_JOB_INTERRUPTED_NS, self._handle_job_interrupted)
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cleanup listeners when entity is removed from hass."""
        for unsub in self._listeners:
            try:
                unsub()
            except Exception:
                # ignore errors during cleanup
                pass
        self._listeners.clear()

    def start_process(self, name: str) -> None:
        """Mark a subprocess as started."""
        self._active_processes.add(name)
        self._attr_native_value = "working"
        self._attr_extra_state_attributes["subprocess"] = name
        self._attr_extra_state_attributes["active_processes"] = list(self._active_processes)
        self._attr_extra_state_attributes["last_changed"] = datetime.now().isoformat()
        # async_write_ha_state must be called on the event loop thread
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
        # async_write_ha_state must be called on the event loop thread
        self.async_write_ha_state()

    def _handle_job_completed(self, event: Event) -> None:
        """Handle integration job completed event and set last_job to 'done'."""
        try:
            self._attr_extra_state_attributes["last_job"] = "done"
            self._attr_extra_state_attributes["last_changed"] = datetime.now().isoformat()
            self.async_write_ha_state()
        except Exception:
            # Do not raise in event handler
            return

    def _handle_job_interrupted(self, event: Event) -> None:
        """Handle job_interrupted event and set last_job to 'interrupted'."""
        try:
            self._attr_extra_state_attributes["last_job"] = "interrupted"
            self._attr_extra_state_attributes["last_changed"] = datetime.now().isoformat()
            self.async_write_ha_state()
        except Exception:
            return

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for grouping in HA UI."""
        return DeviceInfo(
            identifiers={(DOMAIN, "media_downloader_status")},
            name="Media Downloader",
            manufacturer="Geek-MD",
        )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Media Downloader sensor for a config entry."""
    # Ensure domain storage exists
    hass.data.setdefault(DOMAIN, {})
    sensor = hass.data[DOMAIN].get("status_sensor")
    if sensor is None:
        sensor = MediaDownloaderStatusSensor(hass)
        hass.data[DOMAIN]["status_sensor"] = sensor
    async_add_entities([sensor])
