"""Tests for the gateway integration module.

These tests use a mock EventBus to avoid requiring gateway dependencies.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from oi_dashboard import DashboardIntegration
from oi_dashboard.gateway_integration import (
    DashboardEventSink,
    DashboardIntegration as IntegrationModuleExport,
)


class RecordingSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def on_device_online(self, device_id: str, payload: dict[str, object]) -> None:
        self.calls.append(("device_online", device_id, payload))

    def on_device_offline(self, device_id: str) -> None:
        self.calls.append(("device_offline", device_id, None))

    def on_state_updated(self, device_id: str, state: dict[str, object]) -> None:
        self.calls.append(("state_updated", device_id, state))

    def on_transcript(self, device_id: str, payload: dict[str, object]) -> None:
        self.calls.append(("transcript", device_id, payload))

    def on_agent_response(self, device_id: str, payload: dict[str, object]) -> None:
        self.calls.append(("agent_response", device_id, payload))

    def on_audio_delivered(self, device_id: str, payload: dict[str, object]) -> None:
        self.calls.append(("audio_delivered", device_id, payload))


class MockEventBus:
    """Mock EventBus that tracks subscriptions."""
    
    def __init__(self):
        self._subscribers = []
    
    def subscribe(self, callback):
        self._subscribers.append(callback)
    
    def unsubscribe(self, callback):
        if callback in self._subscribers:
            self._subscribers.remove(callback)
    
    def emit(self, event_type, device_id, payload):
        for sub in self._subscribers:
            sub(event_type, device_id, payload)


def test_package_exports_dashboard_integration() -> None:
    assert DashboardIntegration is IntegrationModuleExport


def test_dashboard_event_sink_protocol_accepts_non_dashboard_objects() -> None:
    sink: DashboardEventSink = RecordingSink()

    sink.on_device_online("device-1", {"device_id": "device-1"})

    assert sink.calls == [("device_online", "device-1", {"device_id": "device-1"})]


class TestDashboardIntegration:
    async def test_integration_subscribes_to_event_bus(self, dashboard):
        """Integration should subscribe to event bus on start."""
        mock_bus = MockEventBus()
        integration = DashboardIntegration(dashboard, mock_bus)
        
        integration.start()
        
        assert len(mock_bus._subscribers) == 1

    async def test_integration_unsubscribes_on_stop(self, dashboard):
        """Integration should unsubscribe from event bus on stop."""
        mock_bus = MockEventBus()
        integration = DashboardIntegration(dashboard, mock_bus)
        
        integration.start()
        integration.stop()
        
        assert len(mock_bus._subscribers) == 0

    async def test_forwards_device_online_event(self, dashboard):
        """Integration should forward device online events."""
        mock_bus = MockEventBus()
        integration = DashboardIntegration(dashboard, mock_bus)
        
        integration.start()
        
        # Trigger the callback directly via emit
        mock_bus.emit("registry.device_online", "test-device", {
            "device_id": "test-device",
            "device_type": "stick",
        })
        
        assert "test-device" in dashboard.state.devices
        assert dashboard.state.devices["test-device"].online is True

    async def test_forwards_device_offline_event(self, dashboard):
        """Integration should mark device offline."""
        mock_bus = MockEventBus()
        integration = DashboardIntegration(dashboard, mock_bus)
        
        # First bring device online
        dashboard.on_device_online("test-device", {"device_id": "test-device"})
        assert dashboard.state.devices["test-device"].online is True
        
        integration.start()
        
        # Then trigger offline
        mock_bus.emit("registry.device_offline", "test-device", {"device_id": "test-device"})
        
        assert dashboard.state.devices["test-device"].online is False

    async def test_forwards_state_updated_event(self, dashboard):
        """Integration should forward state update events."""
        mock_bus = MockEventBus()
        integration = DashboardIntegration(dashboard, mock_bus)
        
        dashboard.on_device_online("test-device", {"device_id": "test-device"})
        
        integration.start()
        
        mock_bus.emit("registry.state_updated", "test-device", {
            "state": {"mode": "listening"},
        })
        
        assert dashboard.state.devices["test-device"].state["mode"] == "listening"

    async def test_forwards_transcript_event(self, dashboard):
        """Integration should forward transcript events."""
        mock_bus = MockEventBus()
        integration = DashboardIntegration(dashboard, mock_bus)
        
        integration.start()
        
        mock_bus.emit("transcript", "test-device", {
            "cleaned": "Hello",
            "stream_id": "s1",
        })
        
        assert len(dashboard.state.transcripts) == 1
        assert dashboard.state.transcripts[0].transcript == "Hello"

    async def test_forwards_agent_response_event(self, dashboard):
        """Integration should forward agent response events."""
        mock_bus = MockEventBus()
        integration = DashboardIntegration(dashboard, mock_bus)
        
        integration.start()
        
        # Add transcript first
        dashboard.on_transcript("test-device", {"cleaned": "Hello", "stream_id": "stream-1"})
        
        # Then agent responds
        mock_bus.emit("agent_response", "test-device", {
            "transcript": "Hello",
            "response_text": "Hi there!",
            "stream_id": "stream-1",
        })
        
        assert dashboard.state.transcripts[0].response == "Hi there!"

    async def test_forwards_audio_delivered_event(self, dashboard):
        """Integration should forward audio delivered events to the dashboard."""
        mock_bus = MockEventBus()
        integration = DashboardIntegration(dashboard, mock_bus)
        dashboard.on_audio_delivered = MagicMock()

        integration.start()

        mock_bus.emit("audio_delivered", "test-device", {
            "response_id": "resp1",
        })

        dashboard.on_audio_delivered.assert_called_once_with("test-device", {
            "response_id": "resp1",
        })

    async def test_ignores_unknown_event_types(self, dashboard):
        """Integration should ignore unknown event types."""
        mock_bus = MockEventBus()
        integration = DashboardIntegration(dashboard, mock_bus)
        
        integration.start()
        
        # Unknown event type - should not affect state
        initial_count = len(dashboard.state.transcripts)
        mock_bus.emit("unknown.event", "test-device", {"data": "test"})
        
        assert len(dashboard.state.transcripts) == initial_count

    async def test_handles_raw_state_event(self, dashboard):
        """Integration should handle raw DATP state events."""
        mock_bus = MockEventBus()
        integration = DashboardIntegration(dashboard, mock_bus)
        
        dashboard.on_device_online("test-device", {"device_id": "test-device"})
        
        integration.start()
        
        mock_bus.emit("state", "test-device", {
            "mode": "thinking",
            "battery_percent": 75,
        })
        
        assert dashboard.state.devices["test-device"].state["mode"] == "thinking"
        assert dashboard.state.devices["test-device"].state["battery_percent"] == 75
