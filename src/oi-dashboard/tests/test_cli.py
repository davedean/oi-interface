"""Tests for the dashboard CLI."""
from __future__ import annotations

import argparse
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, patch


# Ensure src is on the path
_dashboard_src = Path(__file__).parent.parent / "src"
if str(_dashboard_src) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(_dashboard_src))

from oi_dashboard import cli


def test_parse_args_defaults() -> None:
    with patch.object(sys, "argv", ["oi-dashboard"]):
        args = cli.parse_args()

    assert isinstance(args, argparse.Namespace)
    assert args.api_url == f"http://{cli.DEFAULT_HOST}:{cli.DEFAULT_API_PORT}"
    assert args.host == cli.DEFAULT_HOST
    assert args.port == cli.DEFAULT_DASHBOARD_PORT


def test_parse_args_custom_values() -> None:
    with patch.object(
        sys,
        "argv",
        ["oi-dashboard", "--api-url", "http://gateway:9999", "--host", "0.0.0.0", "--port", "9000"],
    ):
        args = cli.parse_args()

    assert args.api_url == "http://gateway:9999"
    assert args.host == "0.0.0.0"
    assert args.port == 9000


def test_main_runs_dashboard_with_parsed_args() -> None:
    run_dashboard = AsyncMock()

    with patch.object(
        sys,
        "argv",
        ["oi-dashboard", "--api-url", "http://gateway:9999", "--host", "0.0.0.0", "--port", "9000"],
    ), patch("oi_dashboard.cli.run_dashboard", run_dashboard), patch("sys.stdout", new_callable=StringIO) as out:
        cli.main()

    run_dashboard.assert_awaited_once_with(
        api_base_url="http://gateway:9999",
        host="0.0.0.0",
        port=9000,
    )
    output = out.getvalue()
    assert "Starting Oi Dashboard" in output
    assert "http://0.0.0.0:9000" in output


def test_main_handles_keyboard_interrupt() -> None:
    with patch.object(sys, "argv", ["oi-dashboard"]), patch(
        "oi_dashboard.cli.run_dashboard",
        AsyncMock(side_effect=KeyboardInterrupt),
    ), patch("sys.stdout", new_callable=StringIO) as out:
        try:
            cli.main()
        except SystemExit as exc:
            assert exc.code == 0
        else:
            raise AssertionError("main() should exit on KeyboardInterrupt")

    assert "Shutting down" in out.getvalue()
