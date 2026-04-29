"""Simple internal event bus: callable-based pub/sub."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """A DATP event delivered through the internal event bus."""
    type: str          # DATP message type, e.g. "event", "state", "audio_chunk"
    device_id: str
    payload: dict[str, Any]


# Type alias for subscriber callbacks.
Subscriber = Callable[[str, str, dict[str, Any]], None]


class EventBus:
    """Internal pub/sub bus for DATP events.

    Emits to all registered subscribers synchronously from whichever task
    calls :meth:`emit`.  Subscribers are called with
    ``(event_type, device_id, payload)``.
    """

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe(self, callback: Subscriber) -> None:
        """Register ``callback`` to receive all events."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Subscriber) -> None:
        """Remove ``callback`` from the subscriber list."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def emit(self, event_type: str, device_id: str, payload: dict[str, Any]) -> None:
        """Deliver ``(event_type, device_id, payload)`` to every subscriber."""
        for sub in list(self._subscribers):
            try:
                sub(event_type, device_id, payload)
            except Exception:
                logger.exception("EventBus subscriber %r raised on %s", sub, event_type)


# ------------------------------------------------------------------
# Module-level singleton (created lazily so it survives ``from datp.events import get_event_bus``)
# ------------------------------------------------------------------

_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Return the shared module-level EventBus singleton."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
