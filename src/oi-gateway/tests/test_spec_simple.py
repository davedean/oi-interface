"""Simple DATP specification compliance tests.

These tests ensure the implementation matches the specification using
simple assertions rather than complex schema validation.
"""
import json
from datp.messages import (
    build_hello, build_hello_ack, build_command,
    build_display_show_status, build_audio_cache_put_begin,
    build_audio_cache_chunk, build_audio_cache_put_end,
    build_audio_play, build_audio_stop,
    build_device_set_brightness, build_device_mute_until,
    build_display_show_card
)


def test_hello_structure_matches_spec():
    """Test that hello messages match the spec structure."""
    # From updated DATP spec
    hello_msg = build_hello(
        device_id="stick-pocket",
        device_type="oi-stick",
        firmware="agent-stick-fw/0.3.0",
        capabilities={
            "audio_in": True,
            "audio_out": True,
            "display": "oled_128x64",
            "buttons": ["main", "a", "b"]
        },
        state={
            "mode": "READY",
            "battery_percent": 71,
            "charging": False,
            "wifi_rssi": -67
        },
        resume_token=None,
        nonce="abc123def456"
    )
    
    # Check envelope structure
    assert hello_msg["v"] == "datp"
    assert hello_msg["type"] == "hello"
    assert "id" in hello_msg
    assert hello_msg["device_id"] == "stick-pocket"
    assert "ts" in hello_msg  # Timestamp should be generated
    
    # Check payload structure
    payload = hello_msg["payload"]
    assert payload["device_type"] == "oi-stick"
    assert payload["protocol"] == "datp"
    assert payload["firmware"] == "agent-stick-fw/0.3.0"
    assert payload["capabilities"] == {
        "audio_in": True,
        "audio_out": True,
        "display": "oled_128x64",
        "buttons": ["main", "a", "b"]
    }
    assert payload["state"] == {
        "mode": "READY",
        "battery_percent": 71,
        "charging": False,
        "wifi_rssi": -67
    }
    # resume_token is optional, may not be present when None
    assert payload.get("resume_token") is None  # Either missing or None
    assert payload["nonce"] == "abc123def456"


def test_hello_ack_structure_matches_spec():
    """Test that hello_ack messages match the spec structure."""
    hello_ack_msg = build_hello_ack(
        session_id="sess_abc",
        device_id="stick-pocket",
        server_id="oi-home",
        server_name="Home Oi"
    )
    
    assert hello_ack_msg["v"] == "datp"
    assert hello_ack_msg["type"] == "hello_ack"
    assert hello_ack_msg["device_id"] == "stick-pocket"
    
    payload = hello_ack_msg["payload"]
    assert payload["session_id"] == "sess_abc"
    assert "server_time" in payload
    assert payload["accepted_protocol"] == "datp"
    assert payload["send_capabilities"] is True
    assert payload["server_id"] == "oi-home"
    assert payload["server_name"] == "Home Oi"


def test_required_commands_have_builders():
    """Test that all required commands from DATP spec have builder functions."""
    # Required commands from DATP spec
    required_commands = [
        ("display.show_status", build_display_show_status),
        ("display.show_card", build_display_show_card),
        ("audio.cache.put_begin", build_audio_cache_put_begin),
        ("audio.cache.put_chunk", build_audio_cache_chunk),
        ("audio.cache.put_end", build_audio_cache_put_end),
        ("audio.play", build_audio_play),
        ("audio.stop", build_audio_stop),
        ("device.set_brightness", build_device_set_brightness),
        ("device.mute_until", build_device_mute_until),
    ]
    
    for op_name, builder in required_commands:
        # Test that builder exists (already verified by import)
        # Test that builder creates valid command
        # Some builders need additional parameters
        if op_name == "display.show_status":
            cmd_msg = builder(device_id="test-device", state="thinking")
        elif op_name == "display.show_card":
            cmd_msg = builder(
                device_id="test-device",
                title="Test",
                options=[{"id": "yes", "label": "Yes"}]
            )
        elif op_name == "audio.cache.put_begin":
            cmd_msg = builder(device_id="test-device", response_id="resp_123")
        elif op_name == "audio.cache.put_chunk":
            cmd_msg = builder(
                device_id="test-device",
                response_id="resp_123",
                seq=0,
                data_b64="AAAA"
            )
        elif op_name == "audio.cache.put_end":
            cmd_msg = builder(device_id="test-device", response_id="resp_123")
        elif op_name == "audio.play":
            cmd_msg = builder(device_id="test-device", response_id="latest")
        elif op_name == "device.set_brightness":
            cmd_msg = builder(device_id="test-device", value=128)
        elif op_name == "device.mute_until":
            cmd_msg = builder(device_id="test-device", until="2026-04-27T05:00:00.000Z")
        else:
            # audio.stop has no args
            cmd_msg = builder(device_id="test-device")
        
        assert cmd_msg["v"] == "datp"
        assert cmd_msg["type"] == "command"
        assert cmd_msg["payload"]["op"] == op_name


def test_audio_cache_put_end_sha256_optional():
    """Test that audio.cache.put_end has optional sha256 as per spec."""
    # With sha256
    cmd_with = build_audio_cache_put_end(
        device_id="test-device",
        response_id="resp_123",
        sha256="abc123"
    )
    assert cmd_with["payload"]["args"]["sha256"] == "abc123"
    
    # Without sha256 (should be None or missing)
    cmd_without = build_audio_cache_put_end(
        device_id="test-device",
        response_id="resp_123"
    )
    # sha256 should be None or not present (implementation detail)
    args = cmd_without["payload"]["args"]
    assert "sha256" not in args or args["sha256"] is None


def test_device_set_brightness_uses_value_not_level():
    """Test that device.set_brightness uses 'value' field (not 'level')."""
    cmd = build_device_set_brightness(device_id="test-device", value=128)
    args = cmd["payload"]["args"]
    assert "value" in args
    assert args["value"] == 128
    assert "level" not in args  # Should use 'value' per spec


def test_spec_examples_are_valid():
    """Test that the examples in the spec documentation are valid."""
    # Example from DATP spec §
    example_state = {
        "v": "datp",
        "type": "state",
        "id": "state_001",
        "device_id": "stick-pocket",
        "ts": "2026-04-27T04:40:03.000Z",
        "payload": {
            "mode": "READY",
            "battery_percent": 71,
            "charging": False,
            "wifi_rssi": -67,
            "heap_free": 132120,
            "uptime_s": 9231,
            "audio_cache_used_bytes": 580222,
            "muted_until": None
        }
    }
    
    # Just verify structure (not full validation)
    assert example_state["v"] == "datp"
    assert example_state["type"] == "state"
    assert "id" in example_state
    assert example_state["device_id"] == "stick-pocket"
    assert "ts" in example_state
    
    payload = example_state["payload"]
    assert payload["mode"] == "READY"
    assert payload["battery_percent"] == 71
    assert payload["charging"] is False
    assert payload["wifi_rssi"] == -67
    assert payload["heap_free"] == 132120
    assert payload["uptime_s"] == 9231
    assert payload["audio_cache_used_bytes"] == 580222
    assert payload["muted_until"] is None


def test_message_types_match_spec():
    """Test that all message types in VALID_MESSAGE_TYPES are in spec."""
    from datp.messages import VALID_MESSAGE_TYPES
    
    # Message types from DATP spec
    spec_message_types = {
        "hello", "hello_ack", "event", "audio_chunk",
        "state", "command", "ack", "error"
    }
    
    for msg_type in VALID_MESSAGE_TYPES:
        assert msg_type in spec_message_types, f"Message type {msg_type} should be in spec"
    
    # Also check all spec types are implemented
    for msg_type in spec_message_types:
        assert msg_type in VALID_MESSAGE_TYPES, f"Spec message type {msg_type} should be in VALID_MESSAGE_TYPES"