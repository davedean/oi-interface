from __future__ import annotations

import json
from typing import Any, Callable


COMMAND_RESULT_FIELDS = (
    ("state", "State"),
    ("label", "Label"),
    ("minutes", "Minutes"),
    ("until", "Until"),
    ("response_id", "Response ID"),
    ("chunks_sent", "Chunks sent"),
    ("text", "Text"),
)


def format_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2)


def format_human_devices(result: dict[str, Any]) -> str:
    devices = result.get("devices", [])
    if not devices:
        return "No devices online."

    lines = []
    for device in devices:
        lines.extend(_format_device_lines(device))
    return "\n".join(lines) + f"\n\nTotal: {result.get('count', len(devices))} device(s)"


def _format_device_lines(device: dict[str, Any]) -> list[str]:
    online = device.get("online", False)
    device_type = device.get("device_type", "?")
    status = "ONLINE" if online else "OFFLINE"
    lines = [f"  [{status}] {device['device_id']} ({device_type})"]

    capability_summary = _format_capabilities(device.get("capabilities", {}))
    if capability_summary is not None:
        lines.append(f"           capabilities: {capability_summary}")

    muted_until = device.get("muted_until")
    if muted_until:
        lines.append(f"           muted until: {muted_until}")

    state = device.get("state", {})
    if state:
        lines.append(f"           state: {state}")

    return lines


def _format_capabilities(capabilities: dict[str, Any]) -> str | None:
    if not capabilities:
        return None

    max_spoken_seconds = capabilities.get("max_spoken_seconds", "?")
    display = _format_display(capabilities)
    audio_input = "mic" if capabilities.get("has_audio_input") else "none"
    audio_output = "speaker" if capabilities.get("has_audio_output") else "none"
    return (
        f"max_spoken={max_spoken_seconds}s, "
        f"display={display}, "
        f"audio={audio_input}/{audio_output}"
    )


def _format_display(capabilities: dict[str, Any]) -> str:
    if not capabilities.get("supports_display"):
        return "none"
    width = capabilities.get("display_width", 0)
    height = capabilities.get("display_height", 0)
    if width and height:
        return f"{width}x{height}"
    return "yes"


def format_human_status(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Gateway Status: {result.get('status', 'unknown')}",
            f"DATP Server: {'running' if result.get('datp_running') else 'stopped'}",
            f"Devices Online: {result.get('devices_online', 0)}",
            f"Timestamp: {result.get('timestamp', '?')}",
        ]
    )


def format_human_command(result: dict[str, Any]) -> str:
    ok = result.get("ok", False)
    command = result.get("command", "?")
    device_id = result.get("device_id", "?")
    lines = [f"{'✓' if ok else '✗'} {command} → {device_id}"]
    for field_name, label in COMMAND_RESULT_FIELDS:
        value = result.get(field_name)
        if value is not None:
            lines.append(f"  {label}: {value}")
    if not ok:
        lines.append("  ⚠ Command not acknowledged by device")
    return "\n".join(lines)


def print_result(
    result: dict[str, Any],
    human: bool,
    human_formatter: Callable[[dict[str, Any]], str],
) -> None:
    print(human_formatter(result) if human else format_json(result))
