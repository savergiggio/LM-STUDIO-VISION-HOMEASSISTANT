"""Calendar entity exposing remembered vision events as a timeline."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_EVENTS_UPDATED
from .store import EventStore

# Each point-in-time event is shown as a short block on the timeline.
EVENT_DURATION = timedelta(minutes=1)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the timeline calendar (once)."""
    domain_data = hass.data[DOMAIN]
    if domain_data.get("_calendar_added"):
        return
    store: EventStore = domain_data["_store"]
    domain_data["_calendar_added"] = True
    async_add_entities([LMStudioTimelineCalendar(store)])


class LMStudioTimelineCalendar(CalendarEntity):
    """A read-only calendar that lists vision events."""

    _attr_has_entity_name = True
    _attr_name = "Timeline"
    _attr_icon = "mdi:timeline-text"
    _attr_unique_id = f"{DOMAIN}_timeline"

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

    def _to_calendar_event(self, raw: dict[str, Any]) -> CalendarEvent | None:
        start = dt_util.parse_datetime(raw.get("timestamp", ""))
        if start is None:
            return None
        if start.tzinfo is None:
            start = dt_util.as_local(start)
        description = raw.get("summary") or ""
        if raw.get("image_url"):
            description = f"{description}\n{raw['image_url']}".strip()
        return CalendarEvent(
            start=start,
            end=start + EVENT_DURATION,
            summary=raw.get("title") or "Vision event",
            description=description or None,
            location=raw.get("camera") or None,
            uid=raw.get("id"),
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return the most recent event (drives the entity state)."""
        for raw in self._store.events:
            cal_event = self._to_calendar_event(raw)
            if cal_event:
                return cal_event
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return events that fall within the requested window."""
        results: list[CalendarEvent] = []
        for raw in self._store.events:
            cal_event = self._to_calendar_event(raw)
            if cal_event is None:
                continue
            if cal_event.end < start_date or cal_event.start > end_date:
                continue
            results.append(cal_event)
        return results

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
