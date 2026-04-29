"""Fixture loading and replay for oi-sim.

A fixture is a JSONL_ file where each line is a JSON dict representing
one DATP message (typically sent by the gateway to the device during a
recorded session).

Format (gateway → device line):
  {"type": "command", "payload": {"op": "display.show_status", "args": {"state": "thinking"}}}

Format (event line, for timing markers):
  {"type": "delay_ms": 500}   -- sleep before next line

.. _JSONL: https://jsonlines.org/
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator

from sim.sim import OiSim

# ------------------------------------------------------------------
# Loading
# ------------------------------------------------------------------

def load_fixture(path: str) -> list[dict[str, Any]]:
    """Load a JSONL fixture file. Each line is a dict.

    Parameters
    ----------
    path : str
        Path to the JSONL file.

    Returns
    -------
    list[dict]
        List of parsed message dicts.
    """
    result: list[dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Fixture not found: {path!r}")
    with p.open() as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {lineno} of {path!r}: {exc}"
                ) from exc
    return result


# ------------------------------------------------------------------
# Replay
# ------------------------------------------------------------------

async def replay_fixture(
    sim: OiSim,
    fixture_path: str,
    *,
    send_to_device: bool = True,
) -> list[dict[str, Any]]:
    """Play back a fixture file against a connected ``OiSim``.

    Sends each message in the fixture to the device over its WebSocket
    connection (for fixtures captured from a real gateway session) and
    records the device's responses.

    Parameters
    ----------
    sim : OiSim
        A connected OiSim instance.
    fixture_path : str
        Path to the JSONL fixture file.
    send_to_device : bool
        If True, forward fixture lines to the device's socket.
        Set False to inject directly into the device's message processor
        (no live WebSocket needed; acks are still sent if connected).

    Returns
    -------
    list[dict]
        All messages received by the device during replay.
    """
    if not sim._connected or sim._ws is None:
        raise RuntimeError("OiSim must be connected before replay_fixture")

    fixture = load_fixture(fixture_path)
    received: list[dict[str, Any]] = []

    for entry in fixture:
        # Delay marker: {"delay_ms": 500}
        if isinstance(entry, dict) and "delay_ms" in entry:
            await asyncio.sleep(entry["delay_ms"] / 1000.0)
            continue

        if send_to_device:
            # Forward to device's socket (simulate gateway sending to device).
            # The listen loop's _process_message will handle it.
            await sim._ws.send(json.dumps(entry))
        else:
            # Directly inject into the device's message processor so
            # command processing, state machine, and ack sending all run.
            await sim._process_message(entry)

        received.append(entry)

    return received


async def iter_fixture(
    fixture_path: str,
) -> AsyncIterator[dict[str, Any]]:
    """Yield fixture entries one at a time without loading all into memory.

    Useful for large fixtures or live replay against a running server.
    """
    p = Path(fixture_path)
    if not p.exists():
        raise FileNotFoundError(f"Fixture not found: {fixture_path!r}")

    with p.open() as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {lineno} of {fixture_path!r}: {exc}"
                ) from exc
