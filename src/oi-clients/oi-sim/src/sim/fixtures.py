"""Fixture loading and replay for oi-sim.

A fixture is a JSONL_ file where each line is a JSON dict representing
one DATP message (typically sent by the gateway to the device during a
recorded session).

Format (gateway → device line):
  {"v": "datp", "type": "command", "id": "cmd-1", "device_id": "oi-sim-001", "ts": "2026-04-30T00:00:00.000Z", "payload": {"op": "display.show_status", "args": {"state": "thinking"}}}

Format (event line, for timing markers):
  {"delay_ms": 500}   -- sleep before next line

.. _JSONL: https://jsonlines.org/
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Iterator

if TYPE_CHECKING:
    from sim.sim import OiSim

# ------------------------------------------------------------------
# Loading
# ------------------------------------------------------------------

def _iter_fixture_entries(path: str) -> Iterator[dict[str, Any]]:
    """Yield parsed non-blank JSONL entries from a fixture file."""
    fixture_path = Path(path)
    if not fixture_path.exists():
        raise FileNotFoundError(f"Fixture not found: {path!r}")

    with fixture_path.open(encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {lineno} of {path!r}: {exc}"
                ) from exc


def load_fixture(path: str) -> list[dict[str, Any]]:
    """Load a JSONL fixture file. Each line is a dict."""
    return list(_iter_fixture_entries(path))


# ------------------------------------------------------------------
# Replay
# ------------------------------------------------------------------

async def replay_fixture(
    sim: OiSim,
    fixture_path: str,
    *,
    send_to_device: bool = False,
) -> list[dict[str, Any]]:
    """Play back a fixture file against a connected ``OiSim``.

    By default, fixture messages are injected directly into the simulator's
    message processor so command handling, state updates, and local ACKs run
    without requiring gateway support for replay.

    Parameters
    ----------
    sim : OiSim
        A connected OiSim instance.
    fixture_path : str
        Path to the JSONL fixture file.
    send_to_device : bool
        If True, write fixture lines to the simulator's socket as raw DATP
        messages. This is mainly useful with fake sockets in tests.
        Leave False to inject directly into the device's message processor
        (the practical default for real replay).

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
            await sim._ws.send(json.dumps(entry))
        else:
            await sim._process_message(entry)

        received.append(entry)

    return received


async def iter_fixture(
    fixture_path: str,
) -> AsyncIterator[dict[str, Any]]:
    """Yield fixture entries one at a time without loading all into memory.

    Useful for large fixtures or live replay against a running server.
    """
    for entry in _iter_fixture_entries(fixture_path):
        yield entry
