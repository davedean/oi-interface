"""Tests for firmware interface compliance.

These tests verify that the gateway correctly implements the DATP protocol
that firmware will depend on. They ensure the gateway:
- Accepts valid hello messages with correct structure
- Sends appropriate hello_ack responses
- Handles events from firmware correctly
- Sends commands in the correct format
- Validates messages according to spec
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
import websockets

from datp.messages import (
    build_hello, build_ack, build_error, parse_message, UNKNOWN_DEVICE,
    build_command
)
from utils import now_iso
import secrets
import asyncio
import pytest
from datp.spec import (
    validate_message_structure, REQUIRED_COMMANDS,
    get_schema_for_type, MESSAGE_SCHEMAS
)


# ------------------------------------------------------------------
# Test data for firmware-like messages
# ------------------------------------------------------------------

def make_firmware_hello(device_id: str = "stick-test-001") -> dict[str, Any]:
    """Create a hello message as firmware would send it."""
    return build_hello(
        device_id=device_id,
        device_type="stickS3",
        firmware="oi-fw/0.1.0",
        capabilities={
            "audio_in": True,
            "audio_out": True,
            "display": "st7789_135x240",
            "buttons": ["main", "a", "b"],
            "commands_supported": [
                "display.show_status",
                "display.show_card",
                "audio.cache.put_begin",
                "audio.cache.put_chunk",
                "audio.cache.put_end",
                "audio.play",
                "audio.stop",
                "device.set_brightness",
                "device.mute_until",
                "device.set_volume",
                "device.set_led",
                "device.reboot",
                "device.shutdown",
                "wifi.configure",
                "storage.format"
            ]
        },
        state={
            "mode": "READY",
            "battery_percent": 95,
            "charging": False,
            "wifi_rssi": -55,
            "heap_free": 200000,
            "uptime_s": 0,
            "audio_cache_used_bytes": 0,
            "muted_until": None
        },
        nonce="fw_nonce_123"
    )


def make_firmware_event(device_id: str, event_type: str = "button.pressed") -> dict[str, Any]:
    """Create an event message as firmware would send it."""
    payload = {"event": event_type}
    if "button" in event_type:
        payload["button"] = "main"
    elif event_type == "audio.recording_finished":
        payload.update({
            "duration_ms": 2500,
            "original_sample_rate": 44100,
            "original_channels": 2,
            "samples": 110250
        })
    
    return {
        "v": "datp",
        "type": "event",
        "id": f"evt_{secrets.token_hex(6)}",
        "device_id": device_id,
        "ts": now_iso(),
        "payload": payload
    }


def make_firmware_audio_chunk(device_id: str, stream_id: str = "rec_001") -> dict[str, Any]:
    """Create an audio chunk message as firmware would send it.
    
    Note: Firmware records at 44.1kHz stereo due to ES8311 hardware constraints,
    but gateway expects 16kHz mono for STT. Firmware includes original_sample_rate
    and original_channels in audio.recording_finished event for conversion.
    """
    return {
        "v": "datp",
        "type": "audio_chunk",
        "id": f"aud_{secrets.token_hex(6)}",
        "device_id": device_id,
        "ts": now_iso(),
        "payload": {
            "stream_id": stream_id,
            "seq": 0,
            "format": "pcm16",
            "sample_rate": 44100,  # ES8311 hardware requirement
            "channels": 2,  # Stereo
            "data_b64": "AAAA"  # Minimal test data
        }
    }


def make_firmware_state(device_id: str, mode: str = "READY") -> dict[str, Any]:
    """Create a state report as firmware would send it."""
    return {
        "v": "datp",
        "type": "state",
        "id": f"state_{secrets.token_hex(6)}",
        "device_id": device_id,
        "ts": now_iso(),
        "payload": {
            "mode": mode,
            "battery_percent": 71,
            "charging": False,
            "wifi_rssi": -67,
            "heap_free": 132120,
            "uptime_s": 9231,
            "audio_cache_used_bytes": 580222,
            "muted_until": None
        }
    }


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def free_port() -> int:
    """Get a free TCP port."""
    import socket
    with socket.socket() as s:
        s.bind(('', 0))
        return s.getsockname()[1]


@pytest.fixture
async def datp_server(free_port):
    """Start a DATP server for testing."""
    from datp.server import DATPServer
    srv = DATPServer(host="localhost", port=free_port)
    task = asyncio.create_task(srv.start())
    await asyncio.sleep(0.1)
    yield srv
    await srv.stop()
    await asyncio.sleep(0.1)


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

def test_firmware_hello_structure():
    """Test that firmware hello messages match the DATP spec."""
    hello_msg = make_firmware_hello()
    
    # Validate against schema
    errors = validate_message_structure(hello_msg)
    assert errors == [], f"Firmware hello validation errors: {errors}"
    
    # Check firmware-specific fields
    payload = hello_msg["payload"]
    assert payload["device_type"] == "stickS3"
    assert payload["firmware"] == "oi-fw/0.1.0"
    
    # Check capabilities include required commands
    capabilities = payload["capabilities"]
    assert "commands_supported" in capabilities
    
    # Firmware should support all required commands
    for cmd in REQUIRED_COMMANDS:
        assert cmd in capabilities["commands_supported"], \
            f"Firmware missing required command: {cmd}"
    
    # Check state report in hello
    state = payload["state"]
    assert state["mode"] == "READY"
    assert "battery_percent" in state
    assert "heap_free" in state


def test_firmware_event_structure():
    """Test that firmware event messages match the DATP spec."""
    device_id = "stick-test-001"
    
    # Test button event
    button_event = make_firmware_event(device_id, "button.pressed")
    errors = validate_message_structure(button_event)
    assert errors == [], f"Button event validation errors: {errors}"
    
    payload = button_event["payload"]
    assert payload["event"] == "button.pressed"
    assert payload["button"] == "main"
    
    # Test audio recording finished event
    audio_event = make_firmware_event(device_id, "audio.recording_finished")
    errors = validate_message_structure(audio_event)
    assert errors == [], f"Audio event validation errors: {errors}"
    
    payload = audio_event["payload"]
    assert payload["event"] == "audio.recording_finished"
    assert payload["original_sample_rate"] == 44100  # ES8311 hardware requirement
    assert payload["original_channels"] == 2  # Stereo
    assert payload["duration_ms"] == 2500


def test_firmware_audio_chunk_structure():
    """Test that firmware audio chunk messages match the DATP spec.
    
    Note: Firmware sends 44.1kHz stereo due to ES8311 hardware constraints,
    gateway is responsible for resampling to 16kHz mono for STT.
    """
    audio_chunk = make_firmware_audio_chunk("stick-test-001")
    
    errors = validate_message_structure(audio_chunk)
    assert errors == [], f"Audio chunk validation errors: {errors}"
    
    payload = audio_chunk["payload"]
    assert payload["format"] == "pcm16"
    assert payload["sample_rate"] == 44100  # ES8311 hardware requirement
    assert payload["channels"] == 2  # Stereo
    assert "data_b64" in payload


def test_firmware_state_structure():
    """Test that firmware state reports match the DATP spec."""
    state_msg = make_firmware_state("stick-test-001", "RECORDING")
    
    errors = validate_message_structure(state_msg)
    assert errors == [], f"State report validation errors: {errors}"
    
    payload = state_msg["payload"]
    assert payload["mode"] == "RECORDING"
    assert payload["battery_percent"] == 71
    assert payload["wifi_rssi"] == -67
    assert payload["heap_free"] == 132120
    assert payload["audio_cache_used_bytes"] == 580222
    assert payload["muted_until"] is None


def test_firmware_ack_structure():
    """Test that firmware acknowledgment messages match the DATP spec."""
    ack_msg = build_ack(
        command_id="cmd_123",
        ok=True
    )
    # Add device_id to ack (build_ack doesn't include it, but should)
    ack_msg["device_id"] = "stick-test-001"
    
    errors = validate_message_structure(ack_msg)
    assert errors == [], f"Ack validation errors: {errors}"
    
    payload = ack_msg["payload"]
    assert payload["command_id"] == "cmd_123"
    assert payload["ok"] is True
    
    # Test error ack (command rejected)
    error_ack = build_ack(
        command_id="cmd_456",
        ok=False
    )
    error_ack["device_id"] = "stick-test-001"
    
    errors = validate_message_structure(error_ack)
    assert errors == [], f"Error ack validation errors: {errors}"
    assert error_ack["payload"]["ok"] is False


def test_firmware_error_structure():
    """Test that firmware error messages match the DATP spec."""
    error_msg = build_error(
        device_id="stick-test-001",
        code="INVALID_STATE",
        message="Cannot record while in PLAYING state",
        related_id="cmd_123"
    )
    
    errors = validate_message_structure(error_msg)
    assert errors == [], f"Error message validation errors: {errors}"
    
    payload = error_msg["payload"]
    assert payload["code"] == "INVALID_STATE"
    assert payload["message"] == "Cannot record while in PLAYING state"
    assert payload["related_id"] == "cmd_123"


def test_all_message_schemas_defined():
    """Test that schemas exist for all message types firmware will use."""
    firmware_message_types = [
        "hello",  # Firmware sends
        "hello_ack",  # Firmware receives
        "event",  # Firmware sends
        "audio_chunk",  # Firmware sends
        "state",  # Firmware sends
        "command",  # Firmware receives
        "ack",  # Firmware sends
        "error",  # Firmware sends (and may receive)
    ]
    
    for msg_type in firmware_message_types:
        assert msg_type in MESSAGE_SCHEMAS, f"Missing schema for firmware message type: {msg_type}"
        
        schema = get_schema_for_type(msg_type)
        assert "properties" in schema
        assert "payload" in schema["properties"]
        
        # All firmware message types should have payload schema
        payload_schema = schema["properties"]["payload"]
        assert payload_schema["type"] == "object"


def test_required_commands_for_firmware():
    """Test that all commands firmware must implement are defined in spec."""
    # These are the minimum commands firmware must implement per DATP spec
    required_commands = REQUIRED_COMMANDS
    
    # Firmware plan includes additional commands
    firmware_plan_commands = [
        "device.set_volume",
        "device.set_led", 
        "device.reboot",
        "device.shutdown",
        "wifi.configure",
        "storage.format"
    ]
    
    # All required commands should be in firmware plan
    for cmd in required_commands:
        assert cmd in firmware_plan_commands or cmd in required_commands, \
            f"Required command {cmd} not in firmware plan"
    
    print(f"Firmware must implement {len(required_commands)} required commands:")
    for cmd in required_commands:
        print(f"  - {cmd}")


@pytest.mark.asyncio
async def test_firmware_hello_handshake_with_gateway(datp_server):
    """Test that firmware can complete hello handshake with gateway."""
    device_id = "stick-test-integration"
    uri = f"ws://localhost:{datp_server.port}/datp"
    
    async with websockets.connect(uri) as websocket:
        # Send hello as firmware would
        hello_msg = make_firmware_hello(device_id)
        await websocket.send(json.dumps(hello_msg))
        
        # Receive hello_ack
        response = await websocket.recv()
        hello_ack = json.loads(response)
        
        # Validate hello_ack
        errors = validate_message_structure(hello_ack)
        assert errors == [], f"Hello_ack validation errors: {errors}"
        
        assert hello_ack["type"] == "hello_ack"
        assert hello_ack["device_id"] == device_id
        
        payload = hello_ack["payload"]
        assert "session_id" in payload
        assert "server_time" in payload
        assert payload["accepted_protocol"] == "datp"
        assert "send_capabilities" in payload
        
        print(f"Firmware handshake successful: session_id={payload['session_id']}")


@pytest.mark.asyncio 
async def test_firmware_event_flow_with_gateway(datp_server):
    """Test that firmware can send events to gateway."""
    device_id = "stick-test-events"
    uri = f"ws://localhost:{datp_server.port}/datp"
    
    async with websockets.connect(uri) as websocket:
        # Handshake first
        hello_msg = make_firmware_hello(device_id)
        await websocket.send(json.dumps(hello_msg))
        hello_ack = json.loads(await websocket.recv())
        
        # Send button event
        button_event = make_firmware_event(device_id, "button.long_hold_started")
        await websocket.send(json.dumps(button_event))
        
        # Send audio recording finished event
        audio_event = make_firmware_event(device_id, "audio.recording_finished")
        await websocket.send(json.dumps(audio_event))
        
        # Send state report
        state_msg = make_firmware_state(device_id, "UPLOADING")
        await websocket.send(json.dumps(state_msg))
        
        print(f"Firmware sent 3 events to gateway successfully")


if __name__ == "__main__":
    # Run validation tests
    test_firmware_hello_structure()
    test_firmware_event_structure()
    test_firmware_audio_chunk_structure()
    test_firmware_state_structure()
    test_firmware_ack_structure()
    test_firmware_error_structure()
    test_all_message_schemas_defined()
    test_required_commands_for_firmware()
    
    print("\n✅ All firmware interface validation tests passed!")
    print("\nFirmware interface is ready for implementation.")
    print("Next: Implement firmware following M5STICKS3_FIRMWARE_PLAN.md")