"""
DATP Message parsing and building for M5Stack StickS3 firmware.

This module handles the construction and parsing of DATP protocol messages
for communication between the device and gateway.
"""

import ujson
import utime


# Message type constants
TYPE_EVENT = "event"
TYPE_COMMAND = "command"
TYPE_ACK = "ack"
TYPE_STATE = "state"
TYPE_HELLO = "hello"
TYPE_HELLO_ACK = "hello_ack"
TYPE_ERROR = "error"
TYPE_AUDIO_CHUNK = "audio_chunk"

# Protocol version
PROTOCOL_VERSION = "datp"

# Message ID counter for device-originated messages
_msg_counter = 0


def _generate_id(prefix="msg"):
    """Generate a unique message ID."""
    global _msg_counter
    _msg_counter = (_msg_counter + 1) % 100000
    return "{}_{}".format(prefix, _msg_counter)


def _timestamp():
    """Get current ISO timestamp."""
    # MicroPython on ESP32 doesn't have timezone info, use UTC
    import uos
    # Use local time formatted as ISO
    tm = utime.localtime()
    # Format: YYYY-MM-DDTHH:MM:SS
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.000Z".format(
        tm[0], tm[1], tm[2], tm[3], tm[4], tm[5]
    )


def build_hello(device_id: str, device_type: str, firmware: str,
                capabilities: dict, state: dict, resume_token=None,
                nonce: str = None) -> str:
    """
    Build a hello message for initial connection.
    
    Args:
        device_id: Unique device identifier
        device_type: Device type (e.g., "stickS3")
        firmware: Firmware version string
        capabilities: Device capabilities dict
        state: Current device state dict
        resume_token: Optional token for session resumption
        nonce: Optional nonce for this connection
    
    Returns:
        JSON string of the hello message
    """
    if nonce is None:
        # Generate a random nonce (use time-based for simplicity)
        import uhashlib
        import uos
        data = "{}{}".format(device_id, utime.time())
        h = uhashlib.sha256()
        h.update(data.encode())
        nonce = h.hexdigest()[:16]
    
    payload = {
        "device_type": device_type,
        "protocol": "datp",
        "firmware": firmware,
        "capabilities": capabilities,
        "state": state,
        "resume_token": resume_token,
        "nonce": nonce
    }
    
    msg = {
        "v": PROTOCOL_VERSION,
        "type": TYPE_HELLO,
        "id": _generate_id("msg"),
        "device_id": device_id,
        "ts": _timestamp(),
        "payload": payload
    }
    
    return ujson.dumps(msg)


def build_event(device_id: str, event: str, **kwargs) -> str:
    """
    Build an event message.
    
    Args:
        device_id: Device identifier
        event: Event type (e.g., "button.pressed")
        **kwargs: Additional payload fields
    
    Returns:
        JSON string of the event message
    """
    payload = {"event": event}
    payload.update(kwargs)
    
    msg = {
        "v": PROTOCOL_VERSION,
        "type": TYPE_EVENT,
        "id": _generate_id("evt"),
        "device_id": device_id,
        "ts": _timestamp(),
        "payload": payload
    }
    
    return ujson.dumps(msg)


def build_audio_chunk(device_id: str, stream_id: str, seq: int,
                     format: str, sample_rate: int, channels: int,
                     data_b64: str) -> str:
    """
    Build an audio chunk message.
    
    Args:
        device_id: Device identifier
        stream_id: Stream identifier for this recording
        seq: Sequence number of this chunk
        format: Audio format (e.g., "pcm16")
        sample_rate: Sample rate in Hz
        channels: Number of channels
        data_b64: Base64-encoded audio data
    
    Returns:
        JSON string of the audio chunk message
    """
    payload = {
        "stream_id": stream_id,
        "seq": seq,
        "format": format,
        "sample_rate": sample_rate,
        "channels": channels,
        "data_b64": data_b64
    }
    
    msg = {
        "v": PROTOCOL_VERSION,
        "type": TYPE_AUDIO_CHUNK,
        "id": _generate_id("aud"),
        "device_id": device_id,
        "ts": _timestamp(),
        "payload": payload
    }
    
    return ujson.dumps(msg)


def build_audio_recording_finished(device_id: str, stream_id: str,
                                   duration_ms: int,
                                   original_sample_rate: int = 44100,
                                   original_channels: int = 2) -> str:
    """
    Build an audio recording finished event.
    
    Note: The device records at 44.1kHz stereo due to ES8311 hardware constraints,
    but the DATP spec expects 16kHz mono for STT. The gateway will convert.
    
    Args:
        device_id: Device identifier
        stream_id: Stream identifier for this recording
        duration_ms: Recording duration in milliseconds
        original_sample_rate: Actual sample rate (default 44100)
        original_channels: Actual channel count (default 2 for stereo)
    
    Returns:
        JSON string of the recording finished event
    """
    samples = original_channels * original_sample_rate * duration_ms // 1000
    
    payload = {
        "event": "audio.recording_finished",
        "stream_id": stream_id,
        "duration_ms": duration_ms,
        "original_sample_rate": original_sample_rate,
        "original_channels": original_channels,
        "samples": samples
    }
    
    msg = {
        "v": PROTOCOL_VERSION,
        "type": TYPE_EVENT,
        "id": _generate_id("evt"),
        "device_id": device_id,
        "ts": _timestamp(),
        "payload": payload
    }
    
    return ujson.dumps(msg)


def build_state(device_id: str, state: dict) -> str:
    """
    Build a state report message.
    
    Args:
        device_id: Device identifier
        state: State dict with mode, battery, etc.
    
    Returns:
        JSON string of the state message
    """
    msg = {
        "v": PROTOCOL_VERSION,
        "type": TYPE_STATE,
        "id": _generate_id("state"),
        "device_id": device_id,
        "ts": _timestamp(),
        "payload": state
    }
    
    return ujson.dumps(msg)


def build_ack(device_id: str, command_id: str, ok: bool,
              error: str = None) -> str:
    """
    Build an acknowledgment message.
    
    Args:
        device_id: Device identifier
        command_id: ID of the command being acknowledged
        ok: Whether the command succeeded
        error: Optional error message if ok is False
    
    Returns:
        JSON string of the ack message
    """
    payload = {
        "command_id": command_id,
        "ok": ok
    }
    
    if error:
        payload["error"] = error
    
    msg = {
        "v": PROTOCOL_VERSION,
        "type": TYPE_ACK,
        "id": _generate_id("ack"),
        "device_id": device_id,
        "ts": _timestamp(),
        "payload": payload
    }
    
    return ujson.dumps(msg)


def build_error(device_id: str, code: str, message: str,
                related_id: str = None) -> str:
    """
    Build an error message.
    
    Args:
        device_id: Device identifier
        code: Error code (e.g., "INVALID_STATE")
        message: Human-readable error message
        related_id: Optional related message ID
    
    Returns:
        JSON string of the error message
    """
    payload = {
        "code": code,
        "message": message
    }
    
    if related_id:
        payload["related_id"] = related_id
    
    msg = {
        "v": PROTOCOL_VERSION,
        "type": TYPE_ERROR,
        "id": _generate_id("err"),
        "device_id": device_id,
        "ts": _timestamp(),
        "payload": payload
    }
    
    return ujson.dumps(msg)


def parse_message(data: str) -> dict:
    """
    Parse a DATP message from JSON.
    
    Args:
        data: JSON string of the message
    
    Returns:
        Parsed message dict
    
    Raises:
        ValueError: If JSON is invalid or missing required fields
    """
    try:
        msg = ujson.loads(data)
    except ValueError as e:
        raise ValueError("Invalid JSON: {}".format(e))
    
    # Validate required fields
    required = ["v", "type", "id", "device_id"]
    for field in required:
        if field not in msg:
            raise ValueError("Missing required field: {}".format(field))
    
    # Validate protocol version
    if msg["v"] != PROTOCOL_VERSION:
        raise ValueError("Invalid protocol version: {}".format(msg["v"]))
    
    return msg


def get_message_type(msg: dict) -> str:
    """Get the message type from a parsed message."""
    return msg.get("type")


def get_message_payload(msg: dict) -> dict:
    """Get the payload from a parsed message."""
    return msg.get("payload", {})


def get_command_op(msg: dict) -> str:
    """Get the operation from a command message."""
    if get_message_type(msg) != TYPE_COMMAND:
        return None
    payload = get_message_payload(msg)
    return payload.get("op")


def get_command_args(msg: dict) -> dict:
    """Get the arguments from a command message."""
    if get_message_type(msg) != TYPE_COMMAND:
        return {}
    payload = get_message_payload(msg)
    return payload.get("args", {})