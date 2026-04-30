"""Command-handling and error-simulation integration tests for oi-sim."""
from __future__ import annotations

import asyncio

import pytest

from sim.sim import OiSim
from sim.state import State


@pytest.mark.asyncio
async def test_command_set_volume(datp_server):
    """device.set_volume command updates volume property."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-vol")
    await device.connect()
    assert device.volume == 80  # default

    try:
        cmd = {
            "v": "datp",
            "type": "command",
            "id": "cmd_vol",
            "device_id": "oi-sim-vol",
            "ts": "2026-04-27T04:40:00.000Z",
            "payload": {"op": "device.set_volume", "args": {"level": 50}},
        }
        await datp_server.send_to_device("oi-sim-vol", cmd)
        await asyncio.sleep(0.2)

        device.assert_command_received("device.set_volume")
        assert device.volume == 50
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_command_set_led(datp_server):
    """device.set_led command updates LED state."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-led")
    await device.connect()
    assert device.led_enabled is True  # default

    try:
        cmd = {
            "v": "datp",
            "type": "command",
            "id": "cmd_led",
            "device_id": "oi-sim-led",
            "ts": "2026-04-27T04:40:00.000Z",
            "payload": {"op": "device.set_led", "args": {"enabled": False}},
        }
        await datp_server.send_to_device("oi-sim-led", cmd)
        await asyncio.sleep(0.2)

        device.assert_command_received("device.set_led")
        assert device.led_enabled is False
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_command_set_brightness(datp_server):
    """device.set_brightness command updates brightness property."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-bright")
    await device.connect()
    assert device.brightness == 100  # default

    try:
        cmd = {
            "v": "datp",
            "type": "command",
            "id": "cmd_bright",
            "device_id": "oi-sim-bright",
            "ts": "2026-04-27T04:40:00.000Z",
            "payload": {"op": "device.set_brightness", "args": {"value": 50}},
        }
        await datp_server.send_to_device("oi-sim-bright", cmd)
        await asyncio.sleep(0.2)

        device.assert_command_received("device.set_brightness")
        assert device.brightness == 50
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_command_device_reboot(datp_server):
    """device.reboot command transitions to BOOTING state."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-reboot")
    await device.connect()
    device.assert_state(State.READY)

    try:
        cmd = {
            "v": "datp",
            "type": "command",
            "id": "cmd_reboot",
            "device_id": "oi-sim-reboot",
            "ts": "2026-04-27T04:40:00.000Z",
            "payload": {"op": "device.reboot", "args": {}},
        }
        await datp_server.send_to_device("oi-sim-reboot", cmd)
        await asyncio.sleep(0.2)

        device.assert_command_received("device.reboot")
        device.assert_state(State.BOOTING)
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_command_device_shutdown(datp_server):
    """device.shutdown command transitions to OFFLINE state."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-shtdn")
    await device.connect()
    device.assert_state(State.READY)

    try:
        cmd = {
            "v": "datp",
            "type": "command",
            "id": "cmd_shtdn",
            "device_id": "oi-sim-shtdn",
            "ts": "2026-04-27T04:40:00.000Z",
            "payload": {"op": "device.shutdown", "args": {}},
        }
        await datp_server.send_to_device("oi-sim-shtdn", cmd)
        await asyncio.sleep(0.2)

        device.assert_command_received("device.shutdown")
        device.assert_state(State.OFFLINE)
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_command_storage_format(datp_server):
    """storage.format command is accepted (no state change)."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-fmt")
    await device.connect()
    device.assert_state(State.READY)

    try:
        cmd = {
            "v": "datp",
            "type": "command",
            "id": "cmd_fmt",
            "device_id": "oi-sim-fmt",
            "ts": "2026-04-27T04:40:00.000Z",
            "payload": {"op": "storage.format", "args": {}},
        }
        await datp_server.send_to_device("oi-sim-fmt", cmd)
        await asyncio.sleep(0.2)

        device.assert_command_received("storage.format")
        device.assert_state(State.READY)  # state unchanged
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_command_wifi_configure(datp_server):
    """wifi.configure command is accepted (no state change)."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-wfic")
    await device.connect()
    device.assert_state(State.READY)

    try:
        cmd = {
            "v": "datp",
            "type": "command",
            "id": "cmd_wifi",
            "device_id": "oi-sim-wfic",
            "ts": "2026-04-27T04:40:00.000Z",
            "payload": {"op": "wifi.configure", "args": {"ssid": "MyNetwork", "password": "secret"}},
        }
        await datp_server.send_to_device("oi-sim-wfic", cmd)
        await asyncio.sleep(0.2)

        device.assert_command_received("wifi.configure")
        device.assert_state(State.READY)  # state unchanged
    finally:
        await device.disconnect()


# ------------------------------------------------------------------
# Error simulation tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_simulate_network_error(datp_server):
    """simulate_network_error sends a network error event."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-err1")
    await device.connect()

    received_events: list[dict] = []
    def handler(etype, did, payload):
        if etype == "event":
            received_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.simulate_network_error("Connection refused")
        await asyncio.sleep(0.2)
        assert len(received_events) == 1
        assert received_events[0]["event"] == "device.error"
        assert received_events[0]["code"] == "NETWORK_ERROR"
        assert received_events[0]["message"] == "Connection refused"
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_simulate_storage_error(datp_server):
    """simulate_storage_error sends a storage error event."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-err2")
    await device.connect()

    received_events: list[dict] = []
    def handler(etype, did, payload):
        if etype == "event":
            received_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.simulate_storage_error("Write failed")
        await asyncio.sleep(0.2)
        assert len(received_events) == 1
        assert received_events[0]["event"] == "device.error"
        assert received_events[0]["code"] == "STORAGE_ERROR"
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_simulate_audio_error(datp_server):
    """simulate_audio_error sends an audio error event."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-err3")
    await device.connect()

    received_events: list[dict] = []
    def handler(etype, did, payload):
        if etype == "event":
            received_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.simulate_audio_error("Decoder unavailable")
        await asyncio.sleep(0.2)
        assert len(received_events) == 1
        assert received_events[0]["event"] == "device.error"
        assert received_events[0]["code"] == "AUDIO_ERROR"
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_simulate_invalid_state_error(datp_server):
    """simulate_invalid_state puts device in ERROR state."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-err4")
    await device.connect()
    device.assert_state(State.READY)

    received_events: list[dict] = []
    def handler(etype, did, payload):
        if etype == "event":
            received_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.simulate_invalid_state("Invalid state for audio.play")
        device.assert_state(State.ERROR)

        # Verify error event was sent to gateway
        await asyncio.sleep(0.2)
        assert len(received_events) == 1
        assert received_events[0]["event"] == "device.error"
        assert received_events[0]["code"] == "INVALID_STATE"
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_simulate_critical_error(datp_server):
    """simulate_critical_error puts device in ERROR state with custom code."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-err5")
    await device.connect()
    device.assert_state(State.READY)

    received_events: list[dict] = []
    def handler(etype, did, payload):
        if etype == "event":
            received_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.simulate_critical_error("CRITICAL_BATTERY", "Battery voltage too low")
        device.assert_state(State.ERROR)

        # Verify error event was sent to gateway
        await asyncio.sleep(0.2)
        assert len(received_events) == 1
        assert received_events[0]["event"] == "device.error"
        assert received_events[0]["code"] == "CRITICAL_BATTERY"
        assert received_events[0]["message"] == "Battery voltage too low"
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()
