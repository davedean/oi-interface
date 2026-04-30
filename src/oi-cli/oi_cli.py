"""Main CLI entry point for oi-cli.

Usage:
    oi devices                   # list online devices + capabilities
    oi show-status --device X --state Y [--label L]
    oi mute --device X --minutes N
    oi route --device X --text "..."
    oi status                   # gateway health + connected device count
    oi audio-play --device X [--response-id ID]

All commands output JSON by default. Use --human for human-readable output.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.request
import urllib.error
from typing import Any, Callable

DEFAULT_API_BASE = "http://localhost:8788"

# Configure logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger("oi")

COMMAND_RESULT_FIELDS = (
    ("state", "State"),
    ("label", "Label"),
    ("minutes", "Minutes"),
    ("until", "Until"),
    ("response_id", "Response ID"),
    ("chunks_sent", "Chunks sent"),
    ("text", "Text"),
)


# ------------------------------------------------------------------
# HTTP client helpers
# ------------------------------------------------------------------


class APIClient:
    """Lightweight HTTP client for oi-gateway API."""

    def __init__(self, base_url: str = DEFAULT_API_BASE) -> None:
        self.base_url = base_url.rstrip("/")

    @staticmethod
    def _read_json_response(response: Any) -> dict[str, Any]:
        return json.loads(response.read().decode())

    @staticmethod
    def _log_http_error(exc: urllib.error.HTTPError) -> None:
        try:
            error_body = json.loads(exc.read().decode())
            logger.error("API error (%d): %s", exc.code, error_body.get("error", exc.reason))
        except Exception:
            logger.error("HTTP error: %s", exc.reason)

    @staticmethod
    def _exit_for_connection_error(exc: urllib.error.URLError) -> None:
        logger.error("Connection error: %s", exc)
        sys.exit(1)

    def _request_json(self, request: str | urllib.request.Request, timeout: int) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return self._read_json_response(resp)
        except urllib.error.HTTPError as exc:
            self._log_http_error(exc)
            sys.exit(1)
        except urllib.error.URLError as exc:
            self._exit_for_connection_error(exc)

    def get(self, path: str) -> dict[str, Any]:
        """GET request to the API."""
        return self._request_json(f"{self.base_url}{path}", timeout=5)

    def post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        """POST JSON request to the API."""
        body = json.dumps(data).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._request_json(request, timeout=10)


# ------------------------------------------------------------------
# Output formatters
# ------------------------------------------------------------------


def format_json(data: dict[str, Any]) -> str:
    """Format data as JSON."""
    return json.dumps(data, indent=2)


def format_human_devices(result: dict[str, Any]) -> str:
    """Format device list as human-readable text."""
    devices = result.get("devices", [])
    if not devices:
        return "No devices online."

    lines = []
    for dev in devices:
        online = dev.get("online", False)
        dev_type = dev.get("device_type", "?")
        state = dev.get("state", {})
        muted = dev.get("muted_until", None)
        status = "ONLINE" if online else "OFFLINE"
        lines.append(f"  [{status}] {dev['device_id']} ({dev_type})")
        caps = dev.get("capabilities", {})
        if caps:
            max_sec = caps.get("max_spoken_seconds", "?")
            disp = "none"
            if caps.get("supports_display"):
                w = caps.get("display_width", 0)
                h = caps.get("display_height", 0)
                if w and h:
                    disp = f"{w}x{h}"
                else:
                    disp = "yes"
            audio_in = "mic" if caps.get("has_audio_input") else "none"
            audio_out = "speaker" if caps.get("has_audio_output") else "none"
            lines.append(f"           capabilities: max_spoken={max_sec}s, display={disp}, audio={audio_in}/{audio_out}")
        if muted:
            lines.append(f"           muted until: {muted}")
        if state:
            lines.append(f"           state: {state}")
    return "\n".join(lines) + f"\n\nTotal: {result.get('count', len(devices))} device(s)"


def format_human_status(result: dict[str, Any]) -> str:
    """Format gateway status as human-readable text."""
    lines = [
        f"Gateway Status: {result.get('status', 'unknown')}",
        f"DATP Server: {'running' if result.get('datp_running') else 'stopped'}",
        f"Devices Online: {result.get('devices_online', 0)}",
        f"Timestamp: {result.get('timestamp', '?')}",
    ]
    return "\n".join(lines)


def format_human_command(result: dict[str, Any]) -> str:
    """Format a command result as human-readable text."""
    ok = result.get("ok", False)
    cmd = result.get("command", "?")
    device = result.get("device_id", "?")
    status = "✓" if ok else "✗"
    lines = [f"{status} {cmd} → {device}"]
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
    """Print JSON or human-formatted command output."""
    output = human_formatter(result) if human else format_json(result)
    print(output)


def post_device_command(
    client: APIClient,
    device_id: str,
    command_name: str,
    body: dict[str, Any],
    human: bool,
) -> None:
    """Send a device command and print its result."""
    result = client.post(f"/api/devices/{device_id}/commands/{command_name}", body)
    print_result(result, human, format_human_command)


# ------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------


def cmd_devices(client: APIClient, human: bool) -> None:
    """List online devices with their capabilities."""
    print_result(client.get("/api/devices"), human, format_human_devices)


def cmd_status(client: APIClient, human: bool) -> None:
    """Show gateway health and connected device count."""
    print_result(client.get("/api/health"), human, format_human_status)


def cmd_show_status(client: APIClient, device_id: str, state: str, label: str | None, human: bool) -> None:
    """Invoke display.show_status on a device."""
    body: dict[str, Any] = {"state": state}
    if label is not None:
        body["label"] = label
    post_device_command(client, device_id, "show_status", body, human)


def cmd_mute(client: APIClient, device_id: str, minutes: int, human: bool) -> None:
    """Mute a device for a given number of minutes."""
    post_device_command(client, device_id, "mute_until", {"minutes": minutes}, human)


def cmd_route(client: APIClient, device_id: str, text: str, human: bool) -> None:
    """Route TTS audio to a device (TTS + cache)."""
    print_result(
        client.post("/api/route", {"device_id": device_id, "text": text}),
        human,
        format_human_command,
    )


def cmd_audio_play(client: APIClient, device_id: str, response_id: str | None, human: bool) -> None:
    """Play cached audio on a device."""
    body: dict[str, Any] = {}
    if response_id is not None:
        body["response_id"] = response_id
    post_device_command(client, device_id, "audio_play", body, human)


# ------------------------------------------------------------------
# CLI argument parser
# ------------------------------------------------------------------


def add_api_url_argument(
    parser: argparse.ArgumentParser,
    help_text: str,
    default: str | object = DEFAULT_API_BASE,
) -> None:
    """Add the shared API URL override argument to a parser."""
    parser.add_argument(
        "--api-url",
        default=default,
        help=help_text,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oi",
        description="oi-cli — CLI wrapper for oi-gateway resource tree API",
    )
    add_api_url_argument(
        parser,
        f"Base URL of oi-gateway API (default: {DEFAULT_API_BASE})",
    )
    parser.add_argument(
        "--human",
        action="store_true",
        help="Human-readable output instead of JSON",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # oi devices
    p_devices = subparsers.add_parser("devices", help="List online devices + capabilities")
    add_api_url_argument(p_devices, "Override API base URL", default=argparse.SUPPRESS)

    # oi status
    p_status = subparsers.add_parser("status", help="Gateway health + connected device count")
    add_api_url_argument(p_status, "Override API base URL", default=argparse.SUPPRESS)

    # oi show-status
    p_show = subparsers.add_parser("show-status", help="Invoke display.show_status")
    p_show.add_argument("--device", required=True, help="Target device ID")
    p_show.add_argument("--state", required=True, help="Status state (e.g., thinking, idle)")
    p_show.add_argument("--label", help="Optional label text")
    add_api_url_argument(p_show, "Override API base URL", default=argparse.SUPPRESS)

    # oi mute
    p_mute = subparsers.add_parser("mute", help="Mute a device for N minutes")
    p_mute.add_argument("--device", required=True, help="Target device ID")
    p_mute.add_argument("--minutes", required=True, type=int, help="Number of minutes to mute")
    add_api_url_argument(p_mute, "Override API base URL", default=argparse.SUPPRESS)

    # oi route
    p_route = subparsers.add_parser("route", help="TTS + cache audio to device")
    p_route.add_argument("--device", required=True, help="Target device ID")
    p_route.add_argument("--text", required=True, help="Text to synthesize and route")
    add_api_url_argument(p_route, "Override API base URL", default=argparse.SUPPRESS)

    # oi audio-play
    p_play = subparsers.add_parser("audio-play", help="Play cached audio on device")
    p_play.add_argument("--device", required=True, help="Target device ID")
    p_play.add_argument("--response-id", help="Response ID to play (default: latest)")
    add_api_url_argument(p_play, "Override API base URL", default=argparse.SUPPRESS)

    return parser


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------


def run_command(parsed: argparse.Namespace, client: APIClient) -> None:
    """Dispatch a parsed command to the matching handler."""
    if parsed.command == "devices":
        cmd_devices(client, parsed.human)
        return
    if parsed.command == "status":
        cmd_status(client, parsed.human)
        return
    if parsed.command == "show-status":
        cmd_show_status(client, parsed.device, parsed.state, parsed.label, parsed.human)
        return
    if parsed.command == "mute":
        cmd_mute(client, parsed.device, parsed.minutes, parsed.human)
        return
    if parsed.command == "route":
        cmd_route(client, parsed.device, parsed.text, parsed.human)
        return
    if parsed.command == "audio-play":
        cmd_audio_play(client, parsed.device, parsed.response_id, parsed.human)
        return
    raise ValueError(f"Unknown command: {parsed.command}")


def main(args: list[str] | None = None) -> int:
    """Main entry point. Returns exit code."""
    try:
        parser = build_parser()
        parsed = parser.parse_args(args)
    except SystemExit as exc:
        return exc.code if exc.code is not None else 1

    if parsed.debug:
        logger.setLevel(logging.DEBUG)

    client = APIClient(parsed.api_url)

    try:
        run_command(parsed, client)
    except SystemExit:
        raise  # Re-raise SystemExit from client methods
    except Exception as exc:
        logger.error("Unexpected error: %s", exc)
        if parsed.debug:
            import traceback
            traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())