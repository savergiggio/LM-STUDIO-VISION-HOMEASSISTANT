"""Sensor exposing the latest vision event and recent history."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_EVENTS_UPDATED
from .store import EventStore

RECENT_LIMIT = 20


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the last-event sensor (once)."""
    domain_data = hass.data[DOMAIN]
    if domain_data.get("_sensor_added"):
        return
    store: EventStore = domain_data["_store"]
    domain_data["_sensor_added"] = True
    async_add_entities([LMStudioLastEventSensor(store)])


class LMStudioLastEventSensor(SensorEntity):
    """State = title of the latest event; attributes = recent history."""

    _attr_has_entity_name = True
    _attr_name = "Last event"
    _attr_icon = "mdi:eye-check"
    _attr_unique_id = f"{DOMAIN}_last_event"

    def __init__(self, store: EventStore) -> None:
        """Initialize."""
        self._store = store

    @property
    def device_info(self) -> DeviceInfo:
        """Group entities under one device."""
        return DeviceInfo(
            identifiers={(DOMAIN, "hub")},
            name="LM Studio Vision",
            manufacturer="LM Studio",
            model="Vision timeline",
        )

    @property
    def native_value(self) -> str | None:
        """Title of the most recent event (truncated to fit state limits)."""
        if not self._store.events:
            return "No events"
        return (self._store.events[0].get("title") or "Vision event")[:250]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Recent events and useful fields for templates / cards."""
        events = self._store.events
        latest = events[0] if events else {}
        recent = [
            {
                "id": e.get("id"),
                "timestamp": e.get("timestamp"),
                "title": e.get("title"),
                "summary": e.get("summary"),
                "camera": e.get("camera"),
                "image": e.get("image_url"),
            }
            for e in events[:RECENT_LIMIT]
        ]
        return {
            "count": len(events),
            "last_timestamp": latest.get("timestamp"),
            "last_summary": latest.get("summary"),
            "last_camera": latest.get("camera"),
            "last_image": latest.get("image_url"),
            "events": recent,
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to event-store updates."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_EVENTS_UPDATED, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
