from __future__ import annotations

import argparse

from command_catalog import CommandResult, get_command_spec
from gateway_api import GatewayAPI


def execute_command(parsed: argparse.Namespace, gateway: GatewayAPI) -> CommandResult:
    return get_command_spec(parsed.command).execute(parsed, gateway)
