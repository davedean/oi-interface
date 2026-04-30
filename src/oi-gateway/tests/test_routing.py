"""Tests for the routing module."""
from __future__ import annotations

from pathlib import Path

import pytest

# Ensure src is on the path
gateway_src = Path(__file__).parent.parent / "src"
import sys
if str(gateway_src) not in sys.path:
    sys.path.insert(0, str(gateway_src))

from routing import (
    DeviceCapabilities,
    RoutingPolicy,
    RouteRequest,
    route_to_devices,
)
from routing.capabilities import get_capabilities_for_device_type


class TestDeviceCapabilities:
    """Tests for DeviceCapabilities dataclass."""

    def test_default_capabilities(self):
        """Test default capability values."""
        caps = DeviceCapabilities()
        assert caps.max_spoken_seconds == 120.0
        assert caps.supports_confirm_buttons is False
        assert caps.supports_display is False
        assert caps.is_foreground_device is True
        assert caps.is_background_device is False
        assert caps.supports_long_audio is True

    def test_from_dict_with_all_fields(self):
        """Test parsing from dict with all fields."""
        data = {
            "max_spoken_seconds": 60.0,
            "supports_confirm_buttons": True,
            "supports_display": True,
            "is_foreground_device": True,
            "is_background_device": False,
            "supports_long_audio": True,
        }
        caps = DeviceCapabilities.from_dict(data)
        assert caps.max_spoken_seconds == 60.0
        assert caps.supports_confirm_buttons is True
        assert caps.supports_display is True
        assert caps.is_foreground_device is True

    def test_from_dict_with_defaults(self):
        """Test parsing from dict with missing fields uses defaults."""
        data = {"max_spoken_seconds": 30.0}
        caps = DeviceCapabilities.from_dict(data)
        assert caps.max_spoken_seconds == 30.0
        assert caps.supports_confirm_buttons is False  # default
        assert caps.is_foreground_device is True  # default

    def test_from_dict_none(self):
        """Test parsing from None returns defaults."""
        caps = DeviceCapabilities.from_dict(None)
        assert caps.max_spoken_seconds == 120.0

    def test_can_speak_duration(self):
        """Test duration check."""
        caps = DeviceCapabilities(max_spoken_seconds=60.0)
        assert caps.can_speak_duration(30.0) is True
        assert caps.can_speak_duration(60.0) is True
        assert caps.can_speak_duration(61.0) is False

    def test_is_suitable_for_short_response(self):
        """Test short response suitability."""
        foreground = DeviceCapabilities(is_foreground_device=True)
        background = DeviceCapabilities(is_foreground_device=False)
        assert foreground.is_suitable_for_short_response() is True
        assert background.is_suitable_for_short_response() is False

    def test_to_dict(self):
        """Test serialization to dict."""
        caps = DeviceCapabilities(max_spoken_seconds=45.0, supports_display=True)
        data = caps.to_dict()
        assert data["max_spoken_seconds"] == 45.0
        assert data["supports_display"] is True


class TestDeviceCapabilityProfiles:
    """Tests for device type capability profiles."""

    def test_speaker_profile(self):
        """Test speaker device type profile."""
        caps = get_capabilities_for_device_type("speaker")
        assert caps.max_spoken_seconds == 120.0
        assert caps.supports_confirm_buttons is True
        assert caps.is_foreground_device is True

    def test_display_profile(self):
        """Test display device type profile."""
        caps = get_capabilities_for_device_type("display")
        assert caps.supports_display is True
        assert caps.is_foreground_device is True

    def test_dashboard_profile(self):
        """Test dashboard device type profile."""
        caps = get_capabilities_for_device_type("dashboard")
        assert caps.is_background_device is True
        assert caps.is_foreground_device is False
        assert caps.max_spoken_seconds == 300.0

    def test_watch_profile(self):
        """Test watch device type profile."""
        caps = get_capabilities_for_device_type("watch")
        assert caps.max_spoken_seconds == 30.0
        assert caps.supports_long_audio is False

    def test_unknown_profile(self):
        """Test unknown device type falls back to default."""
        caps = get_capabilities_for_device_type("unknown")
        assert caps.is_foreground_device is True

    def test_profile_with_overrides(self):
        """Test profile overrides."""
        caps = get_capabilities_for_device_type("speaker", {"max_spoken_seconds": 30.0})
        assert caps.max_spoken_seconds == 30.0
        assert caps.supports_confirm_buttons is True  # from profile


class TestRouteRequest:
    """Tests for RouteRequest dataclass."""

    def test_explicit_device_ids(self):
        """Test explicit device IDs."""
        req = RouteRequest(text="Hello", device_ids=["dev1", "dev2"])
        assert req.has_explicit_devices is True
        assert req.explicit_device_ids == ["dev1", "dev2"]
        assert req.get_all_device_ids() == ["dev1", "dev2"]

    def test_single_device_id(self):
        """Test single device ID."""
        req = RouteRequest(text="Hello", single_device_id="dev1")
        assert req.has_explicit_devices is False
        assert req.get_all_device_ids() == ["dev1"]

    def test_estimate_duration(self):
        """Test duration estimation."""
        # ~150 words per minute
        req = RouteRequest(text="one two three four five")  # 5 words
        # 5 words / 150 wpm * 60 = 2 seconds
        duration = req.estimate_duration()
        assert 1.5 < duration < 2.5

    def test_long_text(self):
        """Test estimation for longer text."""
        words = " ".join(["word"] * 200)  # 200 words
        req = RouteRequest(text=words)
        duration = req.estimate_duration()
        # 200 words / 150 wpm * 60 = 80 seconds
        assert 70 < duration < 90


class TestRoutingPolicy:
    """Tests for RoutingPolicy class."""

    @pytest.fixture
    def mock_server(self):
        """Create a mock DATP server with device registry."""
        class MockRegistry:
            class MockStore:
                def get_device(self, device_id):
                    return None
            _store = MockStore()

        class MockServer:
            device_registry = {}
            registry = MockRegistry()

        return MockServer()

    def test_empty_registry(self, mock_server):
        """Test routing with no devices."""
        policy = RoutingPolicy(mock_server)
        req = RouteRequest(text="Hello")
        result = policy.evaluate(req)
        assert result.success is False
        assert "No devices available" in result.errors[0]

    def test_explicit_devices_not_found(self, mock_server):
        """Test explicit device selection with missing devices."""
        mock_server.device_registry = {"dev1": {}}
        policy = RoutingPolicy(mock_server)
        req = RouteRequest(text="Hello", device_ids=["dev1", "dev2"])
        result = policy.evaluate(req)
        assert "dev2" in result.errors[0]

    def test_explicit_devices_valid(self, mock_server):
        """Test explicit device selection with valid devices."""
        mock_server.device_registry = {
            "dev1": {"capabilities": {}},
            "dev2": {"capabilities": {}},
        }
        policy = RoutingPolicy(mock_server)
        req = RouteRequest(text="Hello", device_ids=["dev1", "dev2"])
        result = policy.evaluate(req)
        assert result.success is True
        assert set(result.device_ids) == {"dev1", "dev2"}

    def test_single_device_backward_compat(self, mock_server):
        """Test single device_id backward compatibility."""
        mock_server.device_registry = {"dev1": {"capabilities": {}}}
        policy = RoutingPolicy(mock_server)
        req = RouteRequest(text="Hello", single_device_id="dev1")
        result = policy.evaluate(req)
        assert result.success is True
        assert result.device_ids == ["dev1"]

    def test_short_response_single_foreground(self, mock_server):
        """Test short response routes to the first capable foreground device."""
        mock_server.device_registry = {
            "speaker1": {"capabilities": {"is_foreground_device": True, "max_spoken_seconds": 60.0}},
            "speaker2": {"capabilities": {"is_foreground_device": True, "max_spoken_seconds": 60.0}},
        }
        policy = RoutingPolicy(mock_server)
        req = RouteRequest(text="Short message")  # < 100 words
        result = policy.evaluate(req)
        assert result.success is True
        assert result.device_ids == ["speaker1"]
        assert result.is_long_response is False
        assert result.policy_reason.startswith("Short response")

    def test_long_response_multiple_devices(self, mock_server):
        """Test long response routes to multiple devices."""
        mock_server.device_registry = {
            "speaker1": {"capabilities": {"is_foreground_device": True, "max_spoken_seconds": 60.0}},
            "dashboard1": {"capabilities": {"is_background_device": True, "max_spoken_seconds": 300.0}},
        }
        policy = RoutingPolicy(mock_server)
        # Create long text (> 100 words)
        long_text = " ".join(["word"] * 150)
        req = RouteRequest(text=long_text)
        result = policy.evaluate(req)
        assert result.success is True
        assert result.is_long_response is True
        # Should include both devices
        assert "speaker1" in result.device_ids
        assert "dashboard1" in result.device_ids

    def test_force_multiple_short_text(self, mock_server):
        """Test force_multiple routes short text to exact multi-device selection."""
        mock_server.device_registry = {
            "speaker1": {"capabilities": {"is_foreground_device": True, "max_spoken_seconds": 120.0}},
            "dashboard1": {"capabilities": {"is_background_device": True, "max_spoken_seconds": 300.0}},
        }
        policy = RoutingPolicy(mock_server)
        req = RouteRequest(text="Short", force_multiple=True)
        result = policy.evaluate(req)
        assert result.success is True
        assert result.device_ids == ["speaker1", "dashboard1"]
        assert result.policy_reason.startswith("Long response")

    def test_device_duration_capability(self, mock_server):
        """Test devices filtered by max_spoken_seconds."""
        mock_server.device_registry = {
            "short_only": {"capabilities": {"is_foreground_device": True, "max_spoken_seconds": 30.0}},
        }
        policy = RoutingPolicy(mock_server)
        long_text = " ".join(["word"] * 150)  # ~80 seconds
        req = RouteRequest(text=long_text)
        result = policy.evaluate(req)
        assert result.errors == ["No devices can handle ~60s audio duration"]
        assert result.policy_reason == "No devices capable of long response"

    def test_route_to_devices_convenience(self, mock_server):
        """Test convenience function."""
        mock_server.device_registry = {
            "dev1": {"capabilities": {}},
        }
        req = RouteRequest(text="Hello", single_device_id="dev1")
        result = route_to_devices(mock_server, req)
        assert result.success is True
        assert result.device_ids == ["dev1"]
        assert result.policy_reason == "Short response (~0s) routed to foreground device 'dev1'"

    def test_short_response_with_no_suitable_device_reports_exact_error(self, mock_server):
        mock_server.device_registry = {
            "quiet-dashboard": {"capabilities": {"is_foreground_device": False, "is_background_device": False, "max_spoken_seconds": 120.0}},
        }
        policy = RoutingPolicy(mock_server)
        result = policy.evaluate(RouteRequest(text="short"))
        assert result.success is False
        assert result.errors == ["No suitable devices available for short response"]
        assert result.policy_reason == "No suitable devices found"


class TestRoutingPolicyIntegration:
    """Integration tests for routing with real registry structures."""

    def test_foreground_background_categorization(self):
        """Test devices are correctly categorized."""
        caps = DeviceCapabilities(is_foreground_device=True, is_background_device=False)
        assert caps.is_foreground_device is True
        assert caps.is_background_device is False

        caps = DeviceCapabilities(is_foreground_device=False, is_background_device=True)
        assert caps.is_foreground_device is False
        assert caps.is_background_device is True
