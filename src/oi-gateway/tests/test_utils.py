"""Shared test utilities for DATP protocol message factories."""
from __future__ import annotations

from typing import Any
from datp.messages import build_hello


# Standard test device configurations
TEST_DEVICE_TYPES = {
    "test-device": {
        "firmware": "test-fw/1.0.0",
        "capabilities": {
            "audio_in": True,
            "audio_out": True,
            "display": "test_display",
            "buttons": ["test_button"]
        }
    },
    "oi-stick": {
        "firmware": "test-fw/1.0",
        "capabilities": {
            "input": ["hold_to_record"],
            "output": ["tiny_screen", "cached_audio"]
        }
    }
}


def make_hello(
    device_id: str,
    device_type: str = "oi-stick",
    hello_id: str | None = None,
    include_wifi_rssi: bool = True,
) -> dict[str, Any]:
    """Create a hello message for testing.
    
    Args:
        device_id: The device identifier
        device_type: One of "test-device" or "oi-stick" 
        hello_id: Optional explicit message ID (auto-generated if None)
        include_wifi_rssi: Include wifi_rssi in state (some tests omit it)
    
    Returns:
        A DATP hello message dict
    """
    config = TEST_DEVICE_TYPES.get(device_type, TEST_DEVICE_TYPES["oi-stick"])
    
    state = {"mode": "READY", "battery_percent": 85}
    if include_wifi_rssi:
        state["wifi_rssi"] = -60
    
    hello = build_hello(
        device_id=device_id,
        device_type=device_type,
        firmware=config["firmware"],
        capabilities=config["capabilities"],
        state=state,
        nonce="test_nonce"
    )
    
    if hello_id:
        hello["id"] = hello_id
    
    return hello


def make_hello_test_device(device_id: str, hello_id: str = "msg_hello") -> dict[str, Any]:
    """Create a hello message for test-device type (used in test_datp_server.py)."""
    return make_hello(device_id, device_type="test-device", hello_id=hello_id)


def make_hello_oi_stick(device_id: str) -> dict[str, Any]:
    """Create a hello message for oi-stick type (used in integration tests)."""
    return make_hello(device_id, device_type="oi-stick")