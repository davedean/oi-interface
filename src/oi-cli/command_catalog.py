from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Callable

from api_client import DEFAULT_API_BASE
from gateway_api import GatewayAPI
from presentation import format_human_command, format_human_devices, format_human_status


@dataclass(frozen=True)
class CommandResult:
    payload: dict
    human_formatter: Callable[[dict], str]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    help_text: str
    configure_parser: Callable[[argparse.ArgumentParser], None]
    execute: Callable[[argparse.Namespace, GatewayAPI], CommandResult]


def add_api_url_argument(
    parser: argparse.ArgumentParser,
    help_text: str,
    default: str | object = DEFAULT_API_BASE,
) -> None:
    parser.add_argument("--api-url", default=default, help=help_text)


def _add_command_api_url_argument(parser: argparse.ArgumentParser) -> None:
    add_api_url_argument(parser, "Override API base URL", default=argparse.SUPPRESS)


def _add_device_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--device", required=True, help="Target device ID")


def _configure_no_args(parser: argparse.ArgumentParser) -> None:
    _add_command_api_url_argument(parser)


def _configure_show_status(parser: argparse.ArgumentParser) -> None:
    _add_device_argument(parser)
    parser.add_argument("--state", required=True, help="Status state (e.g., thinking, idle)")
    parser.add_argument("--label", help="Optional label text")
    _add_command_api_url_argument(parser)


def _configure_mute(parser: argparse.ArgumentParser) -> None:
    _add_device_argument(parser)
    parser.add_argument("--minutes", required=True, type=int, help="Number of minutes to mute")
    _add_command_api_url_argument(parser)


def _configure_route(parser: argparse.ArgumentParser) -> None:
    _add_device_argument(parser)
    parser.add_argument("--text", required=True, help="Text to synthesize and route")
    _add_command_api_url_argument(parser)


def _configure_audio_play(parser: argparse.ArgumentParser) -> None:
    _add_device_argument(parser)
    parser.add_argument("--response-id", help="Response ID to play (default: latest)")
    _add_command_api_url_argument(parser)


def _devices(parsed: argparse.Namespace, gateway: GatewayAPI) -> CommandResult:
    return CommandResult(gateway.list_devices(), format_human_devices)


def _status(parsed: argparse.Namespace, gateway: GatewayAPI) -> CommandResult:
    return CommandResult(gateway.gateway_status(), format_human_status)


def _show_status(parsed: argparse.Namespace, gateway: GatewayAPI) -> CommandResult:
    return CommandResult(
        gateway.show_status(parsed.device, parsed.state, parsed.label),
        format_human_command,
    )


def _mute(parsed: argparse.Namespace, gateway: GatewayAPI) -> CommandResult:
    return CommandResult(
        gateway.mute_until(parsed.device, parsed.minutes),
        format_human_command,
    )


def _route(parsed: argparse.Namespace, gateway: GatewayAPI) -> CommandResult:
    return CommandResult(gateway.route_text(parsed.device, parsed.text), format_human_command)


def _audio_play(parsed: argparse.Namespace, gateway: GatewayAPI) -> CommandResult:
    return CommandResult(gateway.audio_play(parsed.device, parsed.response_id), format_human_command)


COMMAND_SPECS = [
    CommandSpec("devices", "List online devices + capabilities", _configure_no_args, _devices),
    CommandSpec("status", "Gateway health + connected device count", _configure_no_args, _status),
    CommandSpec("show-status", "Invoke display.show_status", _configure_show_status, _show_status),
    CommandSpec("mute", "Mute a device for N minutes", _configure_mute, _mute),
    CommandSpec("route", "TTS + cache audio to device", _configure_route, _route),
    CommandSpec("audio-play", "Play cached audio on device", _configure_audio_play, _audio_play),
]
COMMAND_SPEC_MAP = {spec.name: spec for spec in COMMAND_SPECS}


def get_command_spec(command_name: str) -> CommandSpec:
    try:
        return COMMAND_SPEC_MAP[command_name]
    except KeyError as exc:
        raise ValueError(f"Unknown command: {command_name}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oi",
        description="oi-cli — CLI wrapper for oi-gateway resource tree API",
    )
    add_api_url_argument(parser, f"Base URL of oi-gateway API (default: {DEFAULT_API_BASE})")
    parser.add_argument("--human", action="store_true", help="Human-readable output instead of JSON")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command", required=True)
    for spec in COMMAND_SPECS:
        subparser = subparsers.add_parser(spec.name, help=spec.help_text)
        spec.configure_parser(subparser)

    return parser
