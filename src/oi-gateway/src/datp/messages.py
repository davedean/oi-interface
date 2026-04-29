"""DATP envelope parsing and validation."""
from __future__ import annotations

import json
import re
import secrets
import uuid
from datetime import datetime
from typing import Any

from utils import now_iso


DATP_VERSION = "datp"
VALID_MESSAGE_TYPES = frozenset([
    "hello",
    "hello_ack",
    "event",
    "audio_chunk",
    "state",
    "ack",
    "command",
    "error",
])

# Sentinel device_id for messages where the device is unknown.
UNKNOWN_DEVICE = "*"

# ISO-8601 timestamp pattern (ms precision, Z suffix).
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def _valid_ts(ts: str) -> bool:
    """Return True if ``ts`` is a valid ISO-8601 timestamp."""
    return bool(_TS_RE.match(ts))


def parse_message(raw_json: str) -> dict[str, Any]:
    """Parse and validate a DATP message.
    
    Args:
        raw_json: Raw JSON string.
    
    Returns:
        The parsed and validated message dict.
        
    Raises:
        ValueError: If message is invalid.
    """
    try:
        msg_dict = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    # Basic validation
    errors = []
    
    # Version is required and must be "datp"
    version = msg_dict.get("v")
    if version is None:
        errors.append("version field is required")
    elif version != DATP_VERSION:
        errors.append(f"Unsupported DATP version: {version!r} (expected 'datp')")
    
    # Required envelope fields
    for field in ("type", "id", "device_id", "ts", "payload"):
        if field not in msg_dict:
            errors.append(f"Missing required field: {field}")
    
    # Validate timestamp format
    if "ts" in msg_dict:
        ts = msg_dict["ts"]
        if not _valid_ts(ts):
            errors.append(f"Invalid timestamp format: {ts!r}")
    
    # Validate message type
    if "type" in msg_dict:
        msg_type = msg_dict["type"]
        if msg_type not in VALID_MESSAGE_TYPES:
            errors.append(f"Unknown message type: {msg_type!r}")
    
    if errors:
        raise ValueError("; ".join(errors))
    
    return msg_dict


def build_hello(
    device_id: str,
    device_type: str,
    firmware: str,
    capabilities: dict[str, Any],
    state: dict[str, Any] | None = None,
    resume_token: str | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Build a hello message for a device to send to the gateway.

    Args:
        device_id: Unique device identifier.
        device_type: Human-readable device type (e.g., "oi-stick", "pi-screen").
        firmware: Firmware version string.
        capabilities: Device capabilities dict.
        state: Optional initial state report.
        resume_token: Optional resume token for session resumption.
        nonce: Optional nonce for replay prevention.

    Returns:
        A complete DATP hello envelope.
    """
    payload: dict[str, Any] = {
        "device_type": device_type,
        "protocol": DATP_VERSION,
        "firmware": firmware,
        "capabilities": capabilities,
    }
    if state:
        payload["state"] = state
    if resume_token:
        payload["resume_token"] = resume_token
    if nonce:
        payload["nonce"] = nonce
    
    return {
        "v": DATP_VERSION,
        "type": "hello",
        "id": f"hello_{secrets.token_hex(6)}",
        "device_id": device_id,
        "ts": now_iso(),
        "payload": payload,
    }


def build_hello_ack(
    session_id: str, 
    device_id: str,
    server_id: str = "oi-home",
    server_name: str = "Home Oi",
    default_agent: dict[str, Any] | None = None,
    available_agents: list[dict[str, Any]] | None = None,
    server_capabilities: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a hello_ack response.

    Args:
        session_id: Unique session identifier assigned by the server.
        device_id: The device's identifier (echoed back).
        server_id: Optional server identifier.
        server_name: Optional human-readable server name.
        default_agent: Optional default agent configuration.
        available_agents: Optional list of available agents.
        server_capabilities: Optional server capabilities.
        policy: Optional policy settings.

    Returns:
        A complete DATP hello_ack envelope.
    """
    server_time = now_iso()
    
    payload: dict[str, Any] = {
        "session_id": session_id,
        "server_time": server_time,
        "accepted_protocol": DATP_VERSION,
        "send_capabilities": True,
        "server_id": server_id,
        "server_name": server_name,
    }
    
    if default_agent:
        payload["default_agent"] = default_agent
    if available_agents:
        payload["available_agents"] = available_agents
    if server_capabilities:
        payload["server_capabilities"] = server_capabilities
    if policy:
        payload["policy"] = policy
    
    return {
        "v": DATP_VERSION,
        "type": "hello_ack",
        "id": f"ha_{session_id[:8]}",
        "device_id": device_id,
        "ts": server_time,
        "payload": payload,
    }


def build_ack(command_id: str, ok: bool) -> dict[str, Any]:
    """Build an acknowledgement response.

    Args:
        command_id: The ID of the command being acknowledged.
        ok: Whether the command succeeded.

    Returns:
        A complete DATP ack envelope.
    """
    return {
        "v": DATP_VERSION,
        "type": "ack",
        "id": f"ack_{command_id[:16]}",
        "device_id": UNKNOWN_DEVICE,
        "ts": now_iso(),
        "payload": {
            "command_id": command_id,
            "ok": ok,
        },
    }


def build_error(
    device_id: str,
    code: str,
    message: str,
    related_id: str | None = None,
) -> dict[str, Any]:
    """Build an error response.

    Args:
        device_id: Target device ID.
        code: Short machine-readable error code.
        message: Human-readable error description.
        related_id: Optional ID of the related message (command, event, etc.).

    Returns:
        A complete DATP error envelope.
    """
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "related_id": related_id,
    }
    return {
        "v": DATP_VERSION,
        "type": "error",
        "id": f"err_{code[:8]}",
        "device_id": device_id,
        "ts": now_iso(),
        "payload": payload,
    }


def build_command(
    device_id: str,
    op: str,
    args: dict[str, Any] | None = None,
    command_id: str | None = None,
) -> dict[str, Any]:
    """Build an outbound DATP command for sending to a device.

    Args:
        device_id: Target device ID.
        op: Command operator, e.g. ``display.show_status``,
            ``audio.play``, ``device.mute_until``.
        args: Command arguments dict.
        command_id: Optional command ID. If omitted, one is generated.

    Returns:
        A complete DATP command envelope.
    """
    return {
        "v": DATP_VERSION,
        "type": "command",
        "id": command_id or f"cmd_{uuid.uuid4().hex[:12]}",
        "device_id": device_id,
        "ts": now_iso(),
        "payload": {
            "op": op,
            "args": args or {},
        },
    }


# ------------------------------------------------------------------
# Convenience builders for specific commands (Step 4+)
# ------------------------------------------------------------------


def build_display_show_status(
    device_id: str,
    state: str,
    label: str | None = None,
) -> dict[str, Any]:
    """Show a semantic status state on the device display."""
    args = {"state": state}
    if label is not None:
        args["label"] = label
    return build_command(device_id, "display.show_status", args)


def build_display_show_card(
    device_id: str,
    title: str,
    options: list[dict[str, Any]],
    body: str | None = None,
) -> dict[str, Any]:
    """Show a confirmation card with button options.
    
    Args:
        device_id: Target device ID.
        title: Card title.
        options: List of button options, each with 'id' and 'label'.
        body: Optional body text to display below title.
    """
    args = {"title": title, "options": options}
    if body is not None:
        args["body"] = body
    return build_command(device_id, "display.show_card", args)


def build_display_show_response_delta(
    device_id: str,
    text_delta: str,
    is_final: bool = False,
    sequence: int | None = None,
) -> dict[str, Any]:
    """Send a final-response text delta during streaming."""
    args: dict[str, Any] = {"text_delta": text_delta, "is_final": is_final}
    if sequence is not None:
        args["sequence"] = sequence
    return build_command(device_id, "display.show_response_delta", args)


def build_display_show_progress(
    device_id: str,
    text: str,
    kind: str | None = None,
    sequence: int | None = None,
) -> dict[str, Any]:
    """Send a progress update while agent is working."""
    args: dict[str, Any] = {"text": text}
    if kind is not None:
        args["kind"] = kind
    if sequence is not None:
        args["sequence"] = sequence
    return build_command(device_id, "display.show_progress", args)


def build_audio_cache_put_begin(
    device_id: str,
    response_id: str,
    format: str = "wav_pcm16",
    sample_rate: int = 22050,
    bytes: int | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """Start an audio cache sequence.
    
    Args:
        device_id: Target device ID.
        response_id: Identifier for this audio response.
        format: Audio format (default: wav_pcm16).
        sample_rate: Sample rate in Hz (default: 22050).
        bytes: Total size in bytes (optional).
        label: Short label for the audio (optional).
    """
    args: dict[str, Any] = {"response_id": response_id, "format": format, "sample_rate": sample_rate}
    if bytes is not None:
        args["bytes"] = bytes
    if label is not None:
        args["label"] = label
    return build_command(device_id, "audio.cache.put_begin", args)


def build_audio_cache_chunk(
    device_id: str,
    response_id: str,
    seq: int,
    data_b64: str,
) -> dict[str, Any]:
    """Send an audio chunk during cache sequence."""
    return build_command(
        device_id,
        "audio.cache.put_chunk",
        {"response_id": response_id, "seq": seq, "data_b64": data_b64},
    )


def build_audio_cache_put_end(device_id: str, response_id: str, sha256: str | None = None) -> dict[str, Any]:
    """Complete an audio cache sequence.
    
    Args:
        device_id: Target device ID.
        response_id: Identifier for this audio response.
        sha256: Optional SHA256 hash of the cached audio for verification.
    """
    args: dict[str, Any] = {"response_id": response_id}
    if sha256 is not None:
        args["sha256"] = sha256
    return build_command(device_id, "audio.cache.put_end", args)


def build_audio_play(device_id: str, response_id: str = "latest") -> dict[str, Any]:
    """Play cached audio on the device."""
    return build_command(device_id, "audio.play", {"response_id": response_id})


def build_audio_stop(device_id: str) -> dict[str, Any]:
    """Stop audio playback."""
    return build_command(device_id, "audio.stop", {})


def build_device_set_brightness(device_id: str, value: int) -> dict[str, Any]:
    """Set device screen brightness (0-255)."""
    return build_command(device_id, "device.set_brightness", {"value": value})


def build_device_mute_until(device_id: str, until: str) -> dict[str, Any]:
    """Mute the device until a specific ISO-8601 timestamp."""
    return build_command(device_id, "device.mute_until", {"until": until})
