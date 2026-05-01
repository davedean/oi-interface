"""Tests for the handheld entrypoint."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, mock_open, patch


client_src = Path(__file__).parent.parent / "generic_sbc_handheld"
if str(client_src) not in sys.path:
    sys.path.insert(0, str(client_src))

import oi_client.__main__ as main_mod


def test_load_config_uses_defaults_when_no_files(monkeypatch) -> None:
    monkeypatch.setattr(main_mod.os.path, "isfile", lambda path: False)

    config, path = main_mod.load_config()

    assert config == main_mod.DEFAULT_CONFIG
    assert path.endswith("config.json")


def test_load_config_prefers_gamedir_file(monkeypatch) -> None:
    payload = {"gateway_url": "ws://remote/datp", "device_id": "dev42"}
    gamedir_path = os.path.join(os.path.dirname(main_mod._SCRIPT_DIR), "config.json")
    monkeypatch.setattr(main_mod.os.path, "isfile", lambda path: path == gamedir_path)

    with patch("builtins.open", mock_open(read_data=json.dumps(payload))):
        config, path = main_mod.load_config()

    assert config["gateway_url"] == "ws://remote/datp"
    assert config["device_id"] == "dev42"
    assert config["device_type"] == main_mod.DEFAULT_CONFIG["device_type"]
    assert path == gamedir_path


def test_config_int_falls_back_on_bad_values() -> None:
    assert main_mod.config_int({"brightness": "oops"}, "brightness") == main_mod.DEFAULT_CONFIG["brightness"]


@patch("oi_client.__main__.setup_logging")
@patch("oi_client.__main__.load_config", return_value=(main_mod.DEFAULT_CONFIG, "/tmp/config.json"))
async def test_main_runs_and_shuts_down_app(mock_load_config, mock_setup_logging, monkeypatch) -> None:
    app = type("App", (), {"run": AsyncMock(), "shutdown": AsyncMock()})()
    captured: dict[str, object] = {}

    def make_app(**kwargs):
        captured.update(kwargs)
        return app

    monkeypatch.setitem(sys.modules, "oi_client.app", type("M", (), {"HandheldApp": make_app}))

    await main_mod.main()

    assert captured["gateway_urls"] == []
    app.run.assert_awaited_once()
    app.shutdown.assert_awaited_once()
