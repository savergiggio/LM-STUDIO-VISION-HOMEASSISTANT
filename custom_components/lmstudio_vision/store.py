"""Persistent event store powering event-memory and the timeline."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import MAX_EVENTS, SIGNAL_EVENTS_UPDATED, STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


class EventStore:
    """In-memory list of vision events backed by HA's Store helper."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the store."""
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self.events: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        """Load events from disk."""
        data = await self._store.async_load()
        self.events = (data or {}).get("events", []) if data else []
        # newest first, defensive sort
        self.events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    async def _async_save(self) -> None:
        await self._store.async_save({"events": self.events})

    @callback
    def _notify(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_EVENTS_UPDATED)

    async def async_add(
        self,
        *,
        title: str,
        summary: str,
        camera: str | None = None,
        model: str | None = None,
        prompt: str | None = None,
        labels: list[str] | None = None,
        image_path: str | None = None,
        image_url: str | None = None,
    ) -> dict[str, Any]:
        """Append a new event and persist it."""
        event = {
            "id": uuid.uuid4().hex,
            "timestamp": dt_util.now().isoformat(),
            "title": (title or "Vision event")[:200],
            "summary": summary or "",
            "camera": camera,
            "model": model,
            "prompt": prompt,
            "labels": labels or [],
            "image_path": image_path,
            "image_url": image_url,
        }
        self.events.insert(0, event)
        if len(self.events) > MAX_EVENTS:
            self.events = self.events[:MAX_EVENTS]
        await self._async_save()
        self._notify()
        return event

    async def async_remove(self, event_id: str) -> bool:
        """Remove a single event by id."""
        before = len(self.events)
        self.events = [e for e in self.events if e.get("id") != event_id]
        if len(self.events) == before:
            return False
        await self._async_save()
        self._notify()
        return True

    async def async_clear(self) -> int:
        """Remove every event. Returns how many were cleared."""
        count = len(self.events)
        self.events = []
        await self._async_save()
        self._notify()
        return count

    def query(
        self,
        *,
        count: int = 10,
        camera: str | None = None,
        after: Any = None,
        before: Any = None,
        text: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return matching events, newest first."""
        results: list[dict[str, Any]] = []
        text_lc = text.lower() if text else None
        for event in self.events:  # already newest-first
            if camera and event.get("camera") != camera:
                continue
            if text_lc and text_lc not in (
                f"{event.get('title', '')} {event.get('summary', '')}".lower()
            ):
                continue
            ts = dt_util.parse_datetime(event.get("timestamp", "")) if event.get(
                "timestamp"
            ) else None
            if after and ts and ts < after:
                continue
            if before and ts and ts > before:
                continue
            results.append(event)
            if len(results) >= count:
                break
        return results

    @staticmethod
    def as_log_text(events: list[dict[str, Any]]) -> str:
        """Render events as a compact chronological log string."""
        lines = []
        for event in reversed(events):  # oldest first for readability
            ts = event.get("timestamp", "")
            cam = f" [{event['camera']}]" if event.get("camera") else ""
            lines.append(f"- {ts}{cam}: {event.get('summary') or event.get('title')}")
        return "\n".join(lines)
