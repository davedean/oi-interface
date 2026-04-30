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

import logging
import sys

from api_client import APIClient, GatewayConnectionError, GatewayRequestError
from command_catalog import DEFAULT_API_BASE, build_parser
from gateway_api import GatewayAPI
from presentation import (
    format_human_command,
    format_human_devices,
    format_human_status,
    print_result,
)
from runner import execute_command


logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger("oi")


def main(args: list[str] | None = None) -> int:
    """Main entry point. Returns exit code."""
    try:
        parser = build_parser()
        parsed = parser.parse_args(args)
    except SystemExit as exc:
        return exc.code if exc.code is not None else 1

    if parsed.debug:
        logger.setLevel(logging.DEBUG)

    gateway = GatewayAPI(APIClient(parsed.api_url))

    try:
        result = execute_command(parsed, gateway)
        print_result(result.payload, parsed.human, result.human_formatter)
    except (GatewayRequestError, GatewayConnectionError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.error("Unexpected error: %s", exc)
        if parsed.debug:
            import traceback

            traceback.print_exc()
        return 1

    return 0


__all__ = [
    "APIClient",
    "DEFAULT_API_BASE",
    "GatewayAPI",
    "build_parser",
    "execute_command",
    "format_human_command",
    "format_human_devices",
    "format_human_status",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
