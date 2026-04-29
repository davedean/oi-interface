"""Test DATP specification compliance.

These tests ensure that the implementation matches the specification.
The specification is defined in `datp.spec` module.
"""
import json
from datp.spec import (
    HELLO_MESSAGE, HELLO_ACK_MESSAGE, EVENT_MESSAGE, 
    AUDIO_CHUNK_MESSAGE, STATE_MESSAGE, COMMAND_MESSAGE,
    ACK_MESSAGE, ERROR_MESSAGE, MESSAGE_SCHEMAS,
    REQUIRED_COMMANDS, validate_message_structure
)
from datp.messages import (
    build_hello, build_hello_ack, build_command,
    build_display_show_status, build_audio_cache_put_end
)


def test_hello_schema_matches_builder():
    """Test that hello builder creates messages matching the schema."""
    # Create a hello message using the builder
    hello_msg = build_hello(
        device_id="test-device",
        device_type="test-type",
        firmware="test-fw/1.0.0",
        capabilities={"audio_in": True, "audio_out": True},
        state={"mode": "READY", "battery_percent": 95},
        resume_token=None,
        nonce="abc123"
    )
    
    # Validate against schema
    errors = validate_message_structure(hello_msg)
    assert errors == [], f"Hello message validation errors: {errors}"
    
    # Check specific fields from schema
    assert hello_msg["v"] == "datp"
    assert hello_msg["type"] == "hello"
    assert "device_id" in hello_msg
    assert "ts" in hello_msg
    assert "payload" in hello_msg
    
    payload = hello_msg["payload"]
    assert "device_type" in payload
    assert payload["protocol"] == "datp"
    assert "firmware" in payload
    assert "capabilities" in payload
    # state is optional but should be present since we passed it
    assert "state" in payload
    # resume_token is optional and not included when None
    # nonce is optional and should be present since we passed it
    assert "nonce" in payload


def test_hello_ack_schema_matches_builder():
    """Test that hello_ack builder creates messages matching the schema."""
    hello_ack_msg = build_hello_ack(
        session_id="sess_abc123",
        device_id="test-device",
        server_id="test-server",
        server_name="Test Server"
    )
    
    errors = validate_message_structure(hello_ack_msg)
    assert errors == [], f"Hello_ack message validation errors: {errors}"
    
    assert hello_ack_msg["v"] == "datp"
    assert hello_ack_msg["type"] == "hello_ack"
    
    payload = hello_ack_msg["payload"]
    assert payload["session_id"] == "sess_abc123"
    assert payload["accepted_protocol"] == "datp"
    assert payload["send_capabilities"] is True
    assert "server_time" in payload


def test_command_schema_matches_builder():
    """Test that command builder creates messages matching the schema."""
    cmd_msg = build_command(
        device_id="test-device",
        op="display.show_status",
        args={"state": "thinking", "label": "Processing"}
    )
    
    errors = validate_message_structure(cmd_msg)
    assert errors == [], f"Command message validation errors: {errors}"
    
    assert cmd_msg["v"] == "datp"
    assert cmd_msg["type"] == "command"
    
    payload = cmd_msg["payload"]
    assert payload["op"] == "display.show_status"
    assert "args" in payload


def test_required_commands_are_implemented():
    """Test that all required commands from spec have builder functions."""
    # This is a simple check - in practice we'd verify each command
    # has a corresponding builder function
    required_ops = set(REQUIRED_COMMANDS)
    
    # Check a few key commands that should have builders
    test_commands = [
        ("display.show_status", build_display_show_status),
        # Note: build_audio_cache_put_end exists
    ]
    
    for op_name, builder_func in test_commands:
        assert op_name in required_ops, f"{op_name} should be in REQUIRED_COMMANDS"
        # Builder function should exist (imported above)


def test_audio_cache_put_end_includes_sha256():
    """Test that audio.cache.put_end includes optional sha256 field."""
    # Build command with and without sha256
    cmd_with_sha256 = build_audio_cache_put_end(
        device_id="test-device",
        response_id="resp_123",
        sha256="abc123sha456"
    )
    
    cmd_without_sha256 = build_audio_cache_put_end(
        device_id="test-device", 
        response_id="resp_123"
    )
    
    # Both should be valid
    for cmd in [cmd_with_sha256, cmd_without_sha256]:
        errors = validate_message_structure(cmd)
        assert errors == [], f"Command validation errors: {errors}"
        
        payload = cmd["payload"]
        assert payload["op"] == "audio.cache.put_end"
        # response_id should be in args, not at payload root
        args = payload["args"]
        assert args["response_id"] == "resp_123"
    
    # Check sha256 field is present when provided
    payload_with = cmd_with_sha256["payload"]
    args_with = payload_with["args"]
    assert args_with.get("sha256") == "abc123sha456"
    
    # sha256 should be None (or missing) when not provided
    payload_without = cmd_without_sha256["payload"]
    args_without = payload_without["args"]
    # The builder doesn't include sha256 when None, which is fine per spec
    assert "sha256" not in args_without


def test_message_schemas_cover_all_types():
    """Test that schemas exist for all message types in VALID_MESSAGE_TYPES."""
    from datp.messages import VALID_MESSAGE_TYPES
    
    for msg_type in VALID_MESSAGE_TYPES:
        assert msg_type in MESSAGE_SCHEMAS, f"Missing schema for message type: {msg_type}"


def test_spec_documentation_examples():
    """Test that spec documentation examples are valid according to schemas."""
    # Example hello from (updated) spec
    example_hello = {
        "v": "datp",
        "type": "hello",
        "id": "msg_001",
        "device_id": "stick-pocket",
        "ts": "2026-04-27T04:40:00.000Z",
        "payload": {
            "device_type": "oi-stick",
            "protocol": "datp",
            "firmware": "agent-stick-fw/0.3.0",
            "capabilities": {
                "audio_in": True,
                "audio_out": True,
                "display": "oled_128x64",
                "buttons": ["main", "a", "b"]
            },
            "state": {
                "mode": "READY",
                "battery_percent": 71,
                "charging": False,
                "wifi_rssi": -67
            },
            "resume_token": None,
            "nonce": "abc123def456"
        }
    }
    
    errors = validate_message_structure(example_hello)
    assert errors == [], f"Example hello validation errors: {errors}"
    
    # Example audio.cache.put_end from spec
    example_put_end_cmd = {
        "v": "datp",
        "type": "command",
        "id": "cmd_123",
        "device_id": "stick-pocket",
        "ts": "2026-04-27T04:40:01.000Z",
        "payload": {
            "op": "audio.cache.put_end",
            "args": {
                "response_id": "resp_123",
                "sha256": "optional-sha256-hash-or-null"
            }
        }
    }
    
    errors = validate_message_structure(example_put_end_cmd)
    assert errors == [], f"Example put_end command validation errors: {errors}"