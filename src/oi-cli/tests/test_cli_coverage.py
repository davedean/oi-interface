from __future__ import annotations

import json
import sys
import urllib.error
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


cli_src = Path(__file__).parent.parent
sys.path.insert(0, str(cli_src))

import oi_cli
from oi_cli import APIClient, build_parser, format_human_devices, format_human_status, main


class ContextResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


class FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, *, body: bytes, reason: str = "bad request", code: int = 400):
        super().__init__(url="http://test", code=code, msg=reason, hdrs=None, fp=None)
        self._body = body

    def read(self):
        return self._body


def test_apiclient_get_uses_base_url_without_trailing_slash() -> None:
    client = APIClient("http://example.test///")

    with patch("urllib.request.urlopen", return_value=ContextResponse({"ok": True})) as urlopen:
        result = client.get("/api/health")

    assert result == {"ok": True}
    urlopen.assert_called_once_with("http://example.test/api/health", timeout=5)


def test_apiclient_get_exits_on_http_error_with_json_body() -> None:
    client = APIClient("http://example.test")
    error = FakeHTTPError(body=b'{"error": "not allowed"}', code=403, reason="forbidden")

    with patch.object(oi_cli.logger, "error") as log_error:
        with patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(SystemExit) as exc:
                client.get("/api/health")

    assert exc.value.code == 1
    log_error.assert_called_once_with("API error (%d): %s", 403, "not allowed")



def test_apiclient_get_exits_on_urlerror() -> None:
    client = APIClient("http://example.test")

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
        with pytest.raises(SystemExit) as exc:
            client.get("/api/health")

    assert exc.value.code == 1


def test_apiclient_post_success_builds_json_request() -> None:
    client = APIClient("http://example.test/")

    with patch("urllib.request.urlopen", return_value=ContextResponse({"ok": True})) as urlopen:
        result = client.post("/api/route", {"text": "hello"})

    assert result == {"ok": True}
    request = urlopen.call_args.args[0]
    assert request.full_url == "http://example.test/api/route"
    assert request.get_method() == "POST"
    assert request.data == b'{"text": "hello"}'
    assert request.headers["Content-type"] == "application/json"
    assert urlopen.call_args.kwargs["timeout"] == 10


def test_apiclient_post_exits_on_http_error_with_json_body() -> None:
    client = APIClient("http://example.test")
    error = FakeHTTPError(body=b'{"error": "not allowed"}', code=403, reason="forbidden")

    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(SystemExit) as exc:
            client.post("/api/route", {"text": "hello"})

    assert exc.value.code == 1


def test_apiclient_post_exits_on_http_error_with_non_json_body() -> None:
    client = APIClient("http://example.test")
    error = FakeHTTPError(body=b"not-json", code=500, reason="server broke")

    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(SystemExit) as exc:
            client.post("/api/route", {"text": "hello"})

    assert exc.value.code == 1


def test_apiclient_post_exits_on_urlerror() -> None:
    client = APIClient("http://example.test")

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
        with pytest.raises(SystemExit) as exc:
            client.post("/api/route", {"text": "hello"})

    assert exc.value.code == 1


def test_format_human_devices_covers_display_audio_and_default_count() -> None:
    output = format_human_devices(
        {
            "devices": [
                {
                    "device_id": "dev-a",
                    "online": True,
                    "device_type": "sim",
                    "capabilities": {
                        "max_spoken_seconds": 42,
                        "supports_display": True,
                        "display_width": 0,
                        "display_height": 0,
                        "has_audio_input": True,
                        "has_audio_output": True,
                    },
                    "state": {"mode": "READY"},
                    "muted_until": "later",
                },
                {
                    "device_id": "dev-b",
                    "online": False,
                    "device_type": "sim",
                    "capabilities": {
                        "max_spoken_seconds": 7,
                        "supports_display": True,
                        "display_width": 64,
                        "display_height": 32,
                        "has_audio_input": False,
                        "has_audio_output": False,
                    },
                    "state": {},
                },
            ]
        }
    )

    assert "display=yes" in output
    assert "display=64x32" in output
    assert "audio=mic/speaker" in output
    assert "audio=none/none" in output
    assert "muted until: later" in output
    assert "state: {'mode': 'READY'}" in output
    assert "Total: 2 device(s)" in output


def test_format_human_status_covers_defaults_and_stopped_state() -> None:
    output = format_human_status({})

    assert "Gateway Status: unknown" in output
    assert "DATP Server: stopped" in output
    assert "Devices Online: 0" in output
    assert "Timestamp: ?" in output


def test_build_parser_supports_debug_and_subcommands() -> None:
    parser = build_parser()

    parsed = parser.parse_args(["--debug", "audio-play", "--device", "dev1", "--response-id", "resp1"])

    assert parsed.debug is True
    assert parsed.command == "audio-play"
    assert parsed.device == "dev1"
    assert parsed.response_id == "resp1"


def test_main_reraises_systemexit_from_command_handler() -> None:
    parser = MagicMock()
    parser.parse_args.return_value = Namespace(command="devices", debug=False, human=False, api_url="http://test")

    with patch("oi_cli.build_parser", return_value=parser):
        with patch("oi_cli.cmd_devices", side_effect=SystemExit(7)):
            with pytest.raises(SystemExit) as exc:
                main([])

    assert exc.value.code == 7


def test_main_returns_one_and_prints_traceback_in_debug_mode() -> None:
    parser = MagicMock()
    parser.parse_args.return_value = Namespace(command="devices", debug=True, human=False, api_url="http://test")

    with patch("oi_cli.build_parser", return_value=parser):
        with patch("oi_cli.cmd_devices", side_effect=RuntimeError("boom")):
            with patch("traceback.print_exc") as print_exc:
                assert main([]) == 1

    print_exc.assert_called_once()
    assert oi_cli.logger.level == oi_cli.logging.DEBUG


def test_main_returns_parser_exit_code_when_argparse_exits() -> None:
    parser = MagicMock()
    parser.parse_args.side_effect = SystemExit(2)

    with patch("oi_cli.build_parser", return_value=parser):
        assert main([]) == 2
