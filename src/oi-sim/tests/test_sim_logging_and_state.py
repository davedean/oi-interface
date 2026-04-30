"""Logging and state-report tests for oi-sim."""
from __future__ import annotations

import asyncio

import pytest

from sim.sim import OiSim
from sim.state import State


@pytest.mark.asyncio
async def test_assert_log_contains(datp_server):
    """assert_log_contains passes when text is in received messages."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-log")
    await device.connect()
    try:
        cmd = {
            "v": "datp", "type": "command", "id": "cmd_log",
            "device_id": "oi-sim-log", "ts": "2026-04-27T04:40:00.000Z",
            "payload": {"op": "display.show_status", "args": {"state": "thinking"}},
        }
        await datp_server.send_to_device("oi-sim-log", cmd)
        await asyncio.sleep(0.2)

        device.assert_log_contains("thinking")
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_send_state_report(datp_server):
    """send_state_report sends a state message to the gateway."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-state")
    await device.connect()

    received_states: list[dict] = []
    def handler(etype, did, payload):
        if etype == "state":
            received_states.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.send_state_report(State.THINKING)
        await asyncio.sleep(0.2)
        assert len(received_states) == 1
        assert received_states[0]["mode"] == "THINKING"
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


# ------------------------------------------------------------------
