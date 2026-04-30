from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import sys


cli_src = Path(__file__).parent.parent
sys.path.insert(0, str(cli_src))

from command_catalog import COMMAND_SPECS, get_command_spec
from gateway_api import GatewayAPI
from presentation import format_human_status
from runner import execute_command


class StubTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def get(self, path: str) -> dict:
        self.calls.append(("GET", path, None))
        return {"status": "ok", "datp_running": True, "devices_online": 1, "timestamp": "now"}

    def post(self, path: str, data: dict) -> dict:
        self.calls.append(("POST", path, data))
        return {"ok": True, "device_id": data.get("device_id", "oi-sim"), "command": path}


def test_command_specs_cover_cli_surface() -> None:
    assert [spec.name for spec in COMMAND_SPECS] == [
        "devices",
        "status",
        "show-status",
        "mute",
        "route",
        "audio-play",
    ]
    assert get_command_spec("route").help_text == "TTS + cache audio to device"


def test_gateway_api_hides_route_and_device_command_paths() -> None:
    transport = StubTransport()
    gateway = GatewayAPI(transport)

    gateway.route_text("oi-sim", "hello")
    gateway.audio_play("oi-sim", "resp-1")

    assert transport.calls == [
        ("POST", "/api/route", {"device_id": "oi-sim", "text": "hello"}),
        (
            "POST",
            "/api/devices/oi-sim/commands/audio_play",
            {"response_id": "resp-1"},
        ),
    ]


def test_execute_command_returns_payload_and_formatter() -> None:
    transport = StubTransport()
    gateway = GatewayAPI(transport)
    parsed = Namespace(command="status", human=True)

    result = execute_command(parsed, gateway)

    assert result.payload["status"] == "ok"
    assert result.human_formatter is format_human_status
    assert transport.calls == [("GET", "/api/health", None)]
