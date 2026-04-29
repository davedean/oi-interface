"""DATP protocol specification defined in code.

This module defines the DATP protocol structure as Python data structures,
serving as the single source of truth for the protocol specification.
"""
import copy
from typing import Any, Dict, List, Optional, Union

# ------------------------------------------------------------------
# DATP Envelope (common to all messages)
# ------------------------------------------------------------------

DATAP_ENVELOPE = {
    "type": "object",
    "required": ["v", "type", "id", "device_id", "ts", "payload"],
    "properties": {
        "v": {
            "type": "string",
            "const": "datp",
            "description": "Protocol version, must be 'datp'"
        },
        "type": {
            "type": "string",
            "enum": ["hello", "hello_ack", "event", "audio_chunk", "state", "command", "ack", "error"],
            "description": "Message type"
        },
        "id": {
            "type": "string",
            "description": "Unique message identifier"
        },
        "device_id": {
            "type": "string",
            "description": "Device identifier"
        },
        "ts": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$",
            "description": "ISO-8601 timestamp with milliseconds, e.g. 2026-04-27T04:40:00.000Z"
        },
        "payload": {
            "type": "object",
            "description": "Message payload (structure depends on type)"
        }
    }
}

# ------------------------------------------------------------------
# Hello Handshake
# ------------------------------------------------------------------

HELLO_PAYLOAD = {
    "type": "object",
    "required": ["device_type", "protocol", "firmware", "capabilities"],
    "properties": {
        "device_type": {
            "type": "string",
            "description": "Human-readable device type, e.g. 'oi-stick', 'pi-screen'"
        },
        "protocol": {
            "type": "string",
            "const": "datp",
            "description": "Protocol identifier, must be 'datp'"
        },
        "firmware": {
            "type": "string",
            "description": "Firmware version string"
        },
        "capabilities": {
            "type": "object",
            "description": "Device capabilities"
        },
        "state": {
            "type": "object",
            "description": "Initial device state (optional)"
        },
        "resume_token": {
            "type": ["string", "null"],
            "description": "Session resumption token (optional)"
        },
        "nonce": {
            "type": "string",
            "description": "Nonce for replay prevention (optional)"
        }
    }
}

HELLO_MESSAGE = copy.deepcopy(DATAP_ENVELOPE)
HELLO_MESSAGE["properties"]["type"]["const"] = "hello"
HELLO_MESSAGE["properties"]["payload"] = HELLO_PAYLOAD

# ------------------------------------------------------------------
# Hello Ack
# ------------------------------------------------------------------

HELLO_ACK_PAYLOAD = {
    "type": "object",
    "required": ["session_id", "server_time", "accepted_protocol", "send_capabilities"],
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Unique session identifier"
        },
        "server_time": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$",
            "description": "Server timestamp (ISO-8601)"
        },
        "accepted_protocol": {
            "type": "string",
            "const": "datp",
            "description": "Accepted protocol, must be 'datp'"
        },
        "send_capabilities": {
            "type": "boolean",
            "description": "Whether to send capabilities"
        },
        "server_id": {
            "type": "string",
            "description": "Server identifier (optional)"
        },
        "server_name": {
            "type": "string",
            "description": "Human-readable server name (optional)"
        },
        "default_agent": {
            "type": "object",
            "description": "Default agent configuration (optional)"
        },
        "available_agents": {
            "type": "array",
            "description": "List of available agents (optional)"
        },
        "server_capabilities": {
            "type": "object",
            "description": "Server capabilities (optional)"
        },
        "policy": {
            "type": "object",
            "description": "Server policy (optional)"
        }
    }
}

HELLO_ACK_MESSAGE = copy.deepcopy(DATAP_ENVELOPE)
HELLO_ACK_MESSAGE["properties"]["type"]["const"] = "hello_ack"
HELLO_ACK_MESSAGE["properties"]["payload"] = HELLO_ACK_PAYLOAD

# ------------------------------------------------------------------
# Event
# ------------------------------------------------------------------

EVENT_PAYLOAD = {
    "type": "object",
    "required": ["event"],
    "properties": {
        "event": {
            "type": "string",
            "description": "Event type, e.g. 'button.long_hold_started', 'audio.recording_finished'"
        },
        "button": {
            "type": "string",
            "description": "Button identifier (for button events)"
        },
        "stream_id": {
            "type": "string",
            "description": "Audio stream identifier (for audio events)"
        },
        "duration_ms": {
            "type": "integer",
            "description": "Duration in milliseconds (for audio events)"
        },
        "original_sample_rate": {
            "type": "integer",
            "description": "Original sample rate (for audio.recording_finished)"
        },
        "original_channels": {
            "type": "integer",
            "description": "Original channel count (for audio.recording_finished)"
        },
        "samples": {
            "type": "integer",
            "description": "Total sample count (for audio.recording_finished)"
        }
    }
}

EVENT_MESSAGE = copy.deepcopy(DATAP_ENVELOPE)
EVENT_MESSAGE["properties"]["type"]["const"] = "event"
EVENT_MESSAGE["properties"]["payload"] = EVENT_PAYLOAD

# ------------------------------------------------------------------
# Audio Chunk
# ------------------------------------------------------------------

AUDIO_CHUNK_PAYLOAD = {
    "type": "object",
    "required": ["stream_id", "seq", "format", "sample_rate", "channels", "data_b64"],
    "properties": {
        "stream_id": {
            "type": "string",
            "description": "Audio stream identifier"
        },
        "seq": {
            "type": "integer",
            "description": "Chunk sequence number (0-indexed)"
        },
        "format": {
            "type": "string",
            "const": "pcm16",
            "description": "Audio format, must be 'pcm16'"
        },
        "sample_rate": {
            "type": "integer",
            "description": "Sample rate in Hz"
        },
        "channels": {
            "type": "integer",
            "description": "Channel count (1=mono, 2=stereo)"
        },
        "data_b64": {
            "type": "string",
            "description": "Base64-encoded PCM audio data"
        }
    }
}

AUDIO_CHUNK_MESSAGE = copy.deepcopy(DATAP_ENVELOPE)
AUDIO_CHUNK_MESSAGE["properties"]["type"]["const"] = "audio_chunk"
AUDIO_CHUNK_MESSAGE["properties"]["payload"] = AUDIO_CHUNK_PAYLOAD

# ------------------------------------------------------------------
# State Report
# ------------------------------------------------------------------

STATE_PAYLOAD = {
    "type": "object",
    "required": ["mode"],
    "properties": {
        "mode": {
            "type": "string",
            "description": "Device mode, e.g. 'READY', 'RECORDING', 'PLAYING'"
        },
        "battery_percent": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "description": "Battery percentage (optional)"
        },
        "charging": {
            "type": "boolean",
            "description": "Whether device is charging (optional)"
        },
        "wifi_rssi": {
            "type": "integer",
            "description": "WiFi signal strength in dBm (optional)"
        },
        "heap_free": {
            "type": "integer",
            "description": "Free heap memory in bytes (optional)"
        },
        "uptime_s": {
            "type": "integer",
            "description": "Uptime in seconds (optional)"
        },
        "audio_cache_used_bytes": {
            "type": "integer",
            "description": "Audio cache usage in bytes (optional)"
        },
        "muted_until": {
            "type": ["string", "null"],
            "description": "Mute expiration timestamp or null (optional)"
        }
    }
}

STATE_MESSAGE = copy.deepcopy(DATAP_ENVELOPE)
STATE_MESSAGE["properties"]["type"]["const"] = "state"
STATE_MESSAGE["properties"]["payload"] = STATE_PAYLOAD

# ------------------------------------------------------------------
# Command (Gateway → Device)
# ------------------------------------------------------------------

COMMAND_PAYLOAD = {
    "type": "object",
    "required": ["op", "args"],
    "properties": {
        "op": {
            "type": "string",
            "description": "Command operation, e.g. 'display.show_status', 'audio.play'"
        },
        "args": {
            "type": "object",
            "description": "Command arguments"
        }
    }
}

COMMAND_MESSAGE = copy.deepcopy(DATAP_ENVELOPE)
COMMAND_MESSAGE["properties"]["type"]["const"] = "command"
COMMAND_MESSAGE["properties"]["payload"] = COMMAND_PAYLOAD

# ------------------------------------------------------------------
# Acknowledgment
# ------------------------------------------------------------------

ACK_PAYLOAD = {
    "type": "object",
    "required": ["command_id", "ok"],
    "properties": {
        "command_id": {
            "type": "string",
            "description": "ID of the command being acknowledged"
        },
        "ok": {
            "type": "boolean",
            "description": "Whether command succeeded"
        }
    }
}

ACK_MESSAGE = copy.deepcopy(DATAP_ENVELOPE)
ACK_MESSAGE["properties"]["type"]["const"] = "ack"
ACK_MESSAGE["properties"]["payload"] = ACK_PAYLOAD

# ------------------------------------------------------------------
# Error
# ------------------------------------------------------------------

ERROR_PAYLOAD = {
    "type": "object",
    "required": ["code", "message"],
    "properties": {
        "code": {
            "type": "string",
            "description": "Error code, e.g. 'INVALID_STATE', 'PROTOCOL_ERROR'"
        },
        "message": {
            "type": "string",
            "description": "Human-readable error description"
        },
        "related_id": {
            "type": ["string", "null"],
            "description": "ID of related message (optional)"
        }
    }
}

ERROR_MESSAGE = copy.deepcopy(DATAP_ENVELOPE)
ERROR_MESSAGE["properties"]["type"]["const"] = "error"
ERROR_MESSAGE["properties"]["payload"] = ERROR_PAYLOAD

# ------------------------------------------------------------------
# Message Type Mapping
# ------------------------------------------------------------------

MESSAGE_SCHEMAS = {
    "hello": HELLO_MESSAGE,
    "hello_ack": HELLO_ACK_MESSAGE,
    "event": EVENT_MESSAGE,
    "audio_chunk": AUDIO_CHUNK_MESSAGE,
    "state": STATE_MESSAGE,
    "command": COMMAND_MESSAGE,
    "ack": ACK_MESSAGE,
    "error": ERROR_MESSAGE,
}

# ------------------------------------------------------------------
# Required Commands
# ------------------------------------------------------------------

REQUIRED_COMMANDS = [
    "display.show_status",
    "display.show_card",
    "audio.cache.put_begin",
    "audio.cache.put_chunk",
    "audio.cache.put_end",
    "audio.play",
    "audio.stop",
    "device.set_brightness",
    "device.mute_until",
]

# Optional commands for advanced features (not required for basic compliance)
OPTIONAL_COMMANDS = [
    "display.show_text_delta",
]

# ------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------

def get_schema_for_type(msg_type: str) -> Dict[str, Any]:
    """Get the JSON schema for a message type.
    
    Args:
        msg_type: DATP message type.
        
    Returns:
        JSON schema for the message type.
        
    Raises:
        ValueError: If msg_type is not a known DATP message type.
    """
    if msg_type not in MESSAGE_SCHEMAS:
        raise ValueError(f"Unknown DATP message type: {msg_type}")
    return MESSAGE_SCHEMAS[msg_type]

def validate_message_structure(message: Dict[str, Any]) -> List[str]:
    """Validate a message against its schema.
    
    Simple structural validation (not full JSON Schema validation).
    
    Args:
        message: DATP message as dictionary.
        
    Returns:
        List of validation errors (empty if valid).
    """
    errors = []
    
    # Check required envelope fields
    for field in ["v", "type", "id", "device_id", "ts", "payload"]:
        if field not in message:
            errors.append(f"Missing required field: {field}")
    
    if errors:
        return errors
    
    # Check version
    if message["v"] != "datp":
        errors.append(f"Invalid version: {message['v']} (expected 'datp')")
    
    # Check message type
    msg_type = message["type"]
    if msg_type not in MESSAGE_SCHEMAS:
        errors.append(f"Unknown message type: {msg_type}")
        return errors
    
    # Get schema for this message type
    schema = MESSAGE_SCHEMAS[msg_type]
    
    # Check required payload fields
    payload = message["payload"]
    payload_schema = schema["properties"]["payload"]
    
    if payload_schema.get("type") == "object":
        required_fields = payload_schema.get("required", [])
        for field in required_fields:
            if field not in payload:
                errors.append(f"Missing required payload field: {field}")
    
    return errors