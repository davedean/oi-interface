"""Gateway integration — hook dashboard into oi-gateway's EventBus.

This module provides a DashboardIntegration class that connects a Dashboard
instance to the gateway's EventBus for real-time event forwarding.

Usage:
    from oi_dashboard import Dashboard, DashboardIntegration
    from datp.events import get_event_bus

    dashboard = get_dashboard()
    integration = DashboardIntegration(dashboard, get_event_bus())
    integration.start()
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

from .dashboard import Dashboard

logger = logging.getLogger(__name__)
IGNORED_EVENT_TYPES = frozenset({"ack", "error", "event"})


class EventBusLike(Protocol):
    """Protocol for event bus objects (duck typing)."""
    def subscribe(self, callback: Callable[[str, str, dict[str, Any]], None]) -> None: ...
    def unsubscribe(self, callback: Callable[[str, str, dict[str, Any]], None]) -> None: ...


class DashboardIntegration:
    """Bridge between oi-gateway EventBus and Dashboard.

    Subscribes to the gateway's EventBus and forwards relevant events to
    the dashboard's event handlers.

    Parameters
    ----------
    dashboard : Dashboard
        The dashboard instance to forward events to.
    event_bus : EventBusLike
        The gateway's EventBus to subscribe to.
    """

    def __init__(self, dashboard: Dashboard, event_bus: EventBusLike) -> None:
        self._dashboard = dashboard
        self._event_bus = event_bus
        self._handlers: dict[str, Callable[[str, dict[str, Any]], None]] = {
            "registry.device_online": self._handle_device_online,
            "registry.device_offline": self._handle_device_offline,
            "registry.state_updated": self._handle_registry_state_updated,
            "state": self._handle_state,
            "transcript": self._handle_transcript,
            "agent_response": self._handle_agent_response,
            "audio_delivered": self._handle_audio_delivered,
        }

    def start(self) -> None:
        """Start forwarding events to the dashboard."""
        self._event_bus.subscribe(self._on_event)
        logger.info("Dashboard integration started")

    def stop(self) -> None:
        """Stop forwarding events."""
        self._event_bus.unsubscribe(self._on_event)
        logger.info("Dashboard integration stopped")

    def _on_event(self, event_type: str, device_id: str, payload: dict[str, Any]) -> None:
        """Route events from the gateway to the dashboard."""
        if event_type in IGNORED_EVENT_TYPES:
            return

        handler = self._handlers.get(event_type)
        if handler is not None:
            handler(device_id, payload)

    def _handle_device_online(self, device_id: str, payload: dict[str, Any]) -> None:
        """Forward a device online event."""
        self._dashboard.on_device_online(device_id, payload)

    def _handle_device_offline(self, device_id: str, payload: dict[str, Any]) -> None:
        """Forward a device offline event while ignoring its payload."""
        del payload
        self._dashboard.on_device_offline(device_id)

    def _handle_registry_state_updated(self, device_id: str, payload: dict[str, Any]) -> None:
        """Forward registry state payloads using the inner state object."""
        self._dashboard.on_state_updated(device_id, payload.get("state", {}))

    def _handle_state(self, device_id: str, payload: dict[str, Any]) -> None:
        """Forward a raw device state payload."""
        self._dashboard.on_state_updated(device_id, payload)

    def _handle_transcript(self, device_id: str, payload: dict[str, Any]) -> None:
        """Forward a transcript event."""
        self._dashboard.on_transcript(device_id, payload)

    def _handle_agent_response(self, device_id: str, payload: dict[str, Any]) -> None:
        """Forward an agent response event."""
        self._dashboard.on_agent_response(device_id, payload)

    def _handle_audio_delivered(self, device_id: str, payload: dict[str, Any]) -> None:
        """Forward an audio delivery event."""
        self._dashboard.on_audio_delivered(device_id, payload)
