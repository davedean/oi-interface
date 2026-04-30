"""Tests for oi-cli."""
from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

# Add cli source to path
cli_src = Path(__file__).parent.parent
sys.path.insert(0, str(cli_src))

from oi_cli import main, APIClient, format_human_devices, format_human_status, format_human_command


# ------------------------------------------------------------------
# Mock HTTP client fixture
# ------------------------------------------------------------------


class MockClient(APIClient):
    """Test client that returns predefined responses without HTTP."""

    def __init__(self, responses: dict[str, dict], base_url: str = "http://test"):
        super().__init__(base_url)
        self._responses = responses
        self.calls: list[tuple[str, str, dict | None]] = []

    def get(self, path: str) -> dict:
        self.calls.append(("GET", path, None))
        key = f"GET:{path}"
        if key not in self._responses:
            return {"error": f"No mock for {key}"}
        return self._responses[key]

    def post(self, path: str, data: dict) -> dict:
        self.calls.append(("POST", path, data))
        key = f"POST:{path}"
        if key not in self._responses:
            return {"error": f"No mock for {key}"}
        return self._responses[key]


# ------------------------------------------------------------------
# Test APIClient
# ------------------------------------------------------------------


class TestAPIClient:
    def test_get_success(self):
        client = MockClient({
            "GET:/api/health": {"status": "ok", "datp_running": True, "devices_online": 1},
        })
        result = client.get("/api/health")
        assert result["status"] == "ok"
        assert result["datp_running"] is True
        assert len(client.calls) == 1
        assert client.calls[0] == ("GET", "/api/health", None)

    def test_post_success(self):
        client = MockClient({
            "POST:/api/devices/oi-sim/commands/mute_until": {"ok": True, "command": "device.mute_until"},
        })
        result = client.post("/api/devices/oi-sim/commands/mute_until", {"minutes": 30})
        assert result["ok"] is True
        assert len(client.calls) == 1
        call_path, call_data = client.calls[0][1], client.calls[0][2]
        assert call_path == "/api/devices/oi-sim/commands/mute_until"
        assert call_data == {"minutes": 30}


# ------------------------------------------------------------------
# Test formatters
# ------------------------------------------------------------------


class TestFormatters:
    def test_format_human_devices_empty(self):
        result = {"devices": [], "count": 0}
        output = format_human_devices(result)
        assert "No devices online" in output

    def test_format_human_devices_single(self):
        result = {
            "devices": [
                {
                    "device_id": "oi-sim",
                    "online": True,
                    "device_type": "sim",
                    "capabilities": {"max_spoken_seconds": 12},
                    "muted_until": None,
                    "state": {},
                }
            ],
            "count": 1,
        }
        output = format_human_devices(result)
        assert "oi-sim" in output
        assert "ONLINE" in output
        assert "1 device" in output

    def test_format_human_devices_multiple(self):
        result = {
            "devices": [
                {
                    "device_id": "stick-001",
                    "online": True,
                    "device_type": "m5stick",
                    "capabilities": {"max_spoken_seconds": 10},
                    "muted_until": "2026-04-28T15:00:00Z",
                    "state": {"mode": "ready"},
                },
                {
                    "device_id": "stick-002",
                    "online": False,
                    "device_type": "m5stick",
                    "capabilities": {},
                    "state": {},
                },
            ],
            "count": 2,
        }
        output = format_human_devices(result)
        assert "stick-001" in output
        assert "stick-002" in output
        assert "ONLINE" in output
        assert "OFFLINE" in output
        assert "muted until" in output

    def test_format_human_status(self):
        result = {
            "status": "ok",
            "datp_running": True,
            "devices_online": 2,
            "timestamp": "2026-04-27T10:00:00Z",
        }
        output = format_human_status(result)
        assert "ok" in output
        assert "running" in output
        assert "2" in output

    def test_format_human_command_ok(self):
        result = {
            "ok": True,
            "device_id": "oi-sim",
            "command": "device.mute_until",
            "minutes": 30,
            "until": "2026-04-28T15:30:00Z",
        }
        output = format_human_command(result)
        assert "✓" in output
        assert "oi-sim" in output
        assert "30" in output

    def test_format_human_command_failed(self):
        result = {
            "ok": False,
            "device_id": "oi-sim",
            "command": "display.show_status",
            "state": "thinking",
        }
        output = format_human_command(result)
        assert "✗" in output
        assert "not acknowledged" in output


# ------------------------------------------------------------------
# Test CLI commands via main()
# ------------------------------------------------------------------


class TestCLICommands:
    """Test CLI commands by mocking the API client."""

    def _run(self, args: list[str], mock_client: MockClient) -> tuple[int, str, str]:
        stdout = StringIO()
        stderr = StringIO()
        with patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr):
            with patch("oi_cli.APIClient", return_value=mock_client):
                exit_code = main(args)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_devices_json(self):
        client = MockClient({
            "GET:/api/devices": {
                "devices": [
                    {"device_id": "oi-sim", "online": True, "device_type": "sim", "capabilities": {}, "state": {}}
                ],
                "count": 1,
            }
        })
        code, out, err = self._run(["devices"], client)
        assert code == 0
        data = json.loads(out)
        assert data["count"] == 1
        assert data["devices"][0]["device_id"] == "oi-sim"

    def test_devices_human(self):
        client = MockClient({
            "GET:/api/devices": {
                "devices": [
                    {"device_id": "oi-sim", "online": True, "device_type": "sim", "capabilities": {}, "state": {}}
                ],
                "count": 1,
            }
        })
        code, out, err = self._run(["--human", "devices"], client)
        assert code == 0
        assert "oi-sim" in out
        assert "ONLINE" in out

    def test_status_json(self):
        client = MockClient({
            "GET:/api/health": {"status": "ok", "datp_running": True, "devices_online": 1, "timestamp": "2026-04-27T10:00:00Z"}
        })
        code, out, err = self._run(["status"], client)
        assert code == 0
        data = json.loads(out)
        assert data["status"] == "ok"
        assert data["datp_running"] is True

    def test_status_human(self):
        client = MockClient({
            "GET:/api/health": {"status": "ok", "datp_running": True, "devices_online": 2, "timestamp": "2026-04-27T10:00:00Z"}
        })
        code, out, err = self._run(["--human", "status"], client)
        assert code == 0
        assert "running" in out
        assert "2" in out

    def test_show_status_json(self):
        client = MockClient({
            "POST:/api/devices/oi-sim/commands/show_status": {
                "ok": True,
                "device_id": "oi-sim",
                "command": "display.show_status",
                "state": "thinking",
                "label": "Working",
            }
        })
        code, out, err = self._run(
            ["show-status", "--device", "oi-sim", "--state", "thinking", "--label", "Working"],
            client,
        )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert data["state"] == "thinking"
        assert data["label"] == "Working"

    def test_show_status_human(self):
        client = MockClient({
            "POST:/api/devices/oi-sim/commands/show_status": {
                "ok": True,
                "device_id": "oi-sim",
                "command": "display.show_status",
                "state": "thinking",
                "label": None,
            }
        })
        code, out, err = self._run(
            ["--human", "show-status", "--device", "oi-sim", "--state", "thinking"],
            client,
        )
        assert code == 0
        assert "thinking" in out
        assert "✓" in out

    def test_mute_json(self):
        client = MockClient({
            "POST:/api/devices/oi-sim/commands/mute_until": {
                "ok": True,
                "device_id": "oi-sim",
                "command": "device.mute_until",
                "minutes": 30,
                "until": "2026-04-28T15:00:00Z",
            }
        })
        code, out, err = self._run(
            ["mute", "--device", "oi-sim", "--minutes", "30"],
            client,
        )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert data["minutes"] == 30

    def test_mute_human(self):
        client = MockClient({
            "POST:/api/devices/oi-sim/commands/mute_until": {
                "ok": True,
                "device_id": "oi-sim",
                "command": "device.mute_until",
                "minutes": 60,
                "until": "2026-04-28T16:00:00Z",
            }
        })
        code, out, err = self._run(
            ["--human", "mute", "--device", "oi-sim", "--minutes", "60"],
            client,
        )
        assert code == 0
        assert "60" in out
        assert "✓" in out

    def test_route_json(self):
        client = MockClient({
            "POST:/api/route": {
                "ok": True,
                "device_id": "oi-sim",
                "response_id": "resp_abc123",
                "text": "Hello world",
                "chunks_sent": 5,
            }
        })
        code, out, err = self._run(
            ["route", "--device", "oi-sim", "--text", "Hello world"],
            client,
        )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True
        assert data["text"] == "Hello world"
        assert data["chunks_sent"] == 5

    def test_route_human(self):
        client = MockClient({
            "POST:/api/route": {
                "ok": True,
                "device_id": "oi-sim",
                "response_id": "resp_abc123",
                "text": "Done",
                "chunks_sent": 3,
            }
        })
        code, out, err = self._run(
            ["--human", "route", "--device", "oi-sim", "--text", "Done"],
            client,
        )
        assert code == 0
        assert "Done" in out
        assert "3" in out  # chunks sent

    def test_audio_play_json(self):
        client = MockClient({
            "POST:/api/devices/oi-sim/commands/audio_play": {
                "ok": True,
                "device_id": "oi-sim",
                "command": "audio.play",
                "response_id": "latest",
            }
        })
        code, out, err = self._run(
            ["audio-play", "--device", "oi-sim"],
            client,
        )
        assert code == 0
        data = json.loads(out)
        assert data["ok"] is True

    def test_audio_play_with_response_id(self):
        client = MockClient({
            "POST:/api/devices/oi-sim/commands/audio_play": {
                "ok": True,
                "device_id": "oi-sim",
                "command": "audio.play",
                "response_id": "resp_xyz789",
            }
        })
        code, out, err = self._run(
            ["audio-play", "--device", "oi-sim", "--response-id", "resp_xyz789"],
            client,
        )
        assert code == 0
        data = json.loads(out)
        assert data["response_id"] == "resp_xyz789"

    def test_api_url_override(self):
        """Test that --api-url overrides the default API base."""
        client = MockClient({
            "GET:/api/health": {"status": "ok", "datp_running": True, "devices_online": 0, "timestamp": ""}
        })
        stdout = StringIO()
        stderr = StringIO()
        with patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr):
            with patch("oi_cli.APIClient", return_value=client) as api_client:
                code = main(["--api-url", "http://custom:9999", "status"])
        assert code == 0
        api_client.assert_called_once_with("http://custom:9999")
        assert client.calls == [("GET", "/api/health", None)]

    def test_api_url_override_after_subcommand(self):
        client = MockClient({
            "GET:/api/health": {"status": "ok", "datp_running": True, "devices_online": 0, "timestamp": ""}
        })
        stdout = StringIO()
        stderr = StringIO()
        with patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr):
            with patch("oi_cli.APIClient", return_value=client) as api_client:
                code = main(["status", "--api-url", "http://custom:9999"])
        assert code == 0
        api_client.assert_called_once_with("http://custom:9999")
        assert client.calls == [("GET", "/api/health", None)]


# ------------------------------------------------------------------
# Test argument parsing
# ------------------------------------------------------------------


class TestArgParsing:
    def test_missing_command_shows_help(self):
        assert main([]) == 2

    def test_missing_device_arg(self):
        assert main(["show-status", "--state", "thinking"]) == 2

    def test_missing_minutes_arg(self):
        assert main(["mute", "--device", "oi-sim"]) == 2

    def test_missing_text_arg(self):
        assert main(["route", "--device", "oi-sim"]) == 2


# ------------------------------------------------------------------
# Test human-readable edge cases
# ------------------------------------------------------------------


class TestHumanEdgeCases:
    def test_devices_no_capabilities(self):
        result = {
            "devices": [
                {"device_id": "dev1", "online": True, "capabilities": {}, "state": {}, "device_type": "test"}
            ],
            "count": 1,
        }
        output = format_human_devices(result)
        assert "dev1" in output

    def test_devices_with_muted_until(self):
        result = {
            "devices": [
                {
                    "device_id": "dev1",
                    "online": True,
                    "device_type": "m5stick",
                    "capabilities": {},
                    "muted_until": "2026-04-28T15:00:00.000Z",
                    "state": {},
                }
            ],
            "count": 1,
        }
        output = format_human_devices(result)
        assert "muted until" in output

    def test_command_result_with_all_fields(self):
        result = {
            "ok": True,
            "device_id": "oi-sim",
            "command": "audio.play",
            "response_id": "resp_123",
            "state": "playing",
            "label": None,
            "minutes": None,
            "until": None,
            "chunks_sent": 10,
            "text": None,
        }
        output = format_human_command(result)
        assert "resp_123" in output
        assert "audio.play" in output
        assert "State: playing" in output
        assert "Chunks sent: 10" in output
        assert "Label:" not in output
        assert "Minutes:" not in output
        assert "Until:" not in output
        assert "Text:" not in output


# ------------------------------------------------------------------
# Test error handling
# ------------------------------------------------------------------


class TestErrorHandling:
    def test_api_returns_error_json(self):
        client = MockClient({
            "GET:/api/devices": {"error": "Device not found"}
        })
        stdout = StringIO()
        stderr = StringIO()
        with patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr):
            with patch("oi_cli.APIClient", return_value=client):
                code = main(["devices"])
        assert code == 0
        assert json.loads(stdout.getvalue()) == {"error": "Device not found"}
