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
        # Registry events
        if event_type == "registry.device_online":
            self._dashboard.on_device_online(device_id, payload)
        elif event_type == "registry.device_offline":
            self._dashboard.on_device_offline(device_id)
        elif event_type == "registry.state_updated":
            state = payload.get("state", {})
            self._dashboard.on_state_updated(device_id, state)

        # DATP events
        elif event_type == "event":
            # Generic event (button press, recording finished, etc.)
            pass  # Could log or display these
        elif event_type == "state":
            # Raw state report from device
            self._dashboard.on_state_updated(device_id, payload)

        # Transcript pipeline events
        elif event_type == "transcript":
            self._dashboard.on_transcript(device_id, payload)
        elif event_type == "agent_response":
            self._dashboard.on_agent_response(device_id, payload)
        elif event_type == "audio_delivered":
            self._dashboard.on_audio_delivered(device_id, payload)

        # Acknowledgements
        elif event_type in ("ack", "error"):
            pass  # Could display command status
