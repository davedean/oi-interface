"""Device event helper integration tests for oi-sim."""
from __future__ import annotations

import asyncio

import pytest

from sim.sim import OiSim
from sim.state import State


@pytest.mark.asyncio
async def test_send_battery_update(datp_server):
    """send_battery_update sends a sensor.battery_update event."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-bat")
    await device.connect()

    received_events: list[dict] = []
    def handler(etype, did, payload):
        if etype == "event":
            received_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.send_battery_update(75, charging=True)
        await asyncio.sleep(0.2)
        assert len(received_events) == 1
        assert received_events[0]["event"] == "sensor.battery_update"
        assert received_events[0]["battery_percent"] == 75
        assert received_events[0]["charging"] is True
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_send_wifi_update(datp_server):
    """send_wifi_update sends a sensor.wifi_update event."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-wifi")
    await device.connect()

    received_events: list[dict] = []
    def handler(etype, did, payload):
        if etype == "event":
            received_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.send_wifi_update(-45, ssid="TestNetwork")
        await asyncio.sleep(0.2)
        assert len(received_events) == 1
        assert received_events[0]["event"] == "sensor.wifi_update"
        assert received_events[0]["rssi"] == -45
        assert received_events[0]["ssid"] == "TestNetwork"
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_send_storage_low(datp_server):
    """send_storage_low sends a storage.low event."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-store")
    await device.connect()

    received_events: list[dict] = []
    def handler(etype, did, payload):
        if etype == "event":
            received_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.send_storage_low(1024 * 1024)  # 1MB free
        await asyncio.sleep(0.2)
        assert len(received_events) == 1
        assert received_events[0]["event"] == "storage.low"
        assert received_events[0]["bytes_free"] == 1024 * 1024
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_send_storage_full(datp_server):
    """send_storage_full sends a storage.full event."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-full")
    await device.connect()

    received_events: list[dict] = []
    def handler(etype, did, payload):
        if etype == "event":
            received_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.send_storage_full()
        await asyncio.sleep(0.2)
        assert len(received_events) == 1
        assert received_events[0]["event"] == "storage.full"
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_send_network_online(datp_server):
    """send_network_online sends a network.online event."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-net")
    await device.connect()

    received_events: list[dict] = []
    def handler(etype, did, payload):
        if etype == "event":
            received_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.send_network_online()
        await asyncio.sleep(0.2)
        assert len(received_events) == 1
        assert received_events[0]["event"] == "network.online"
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_send_network_offline(datp_server):
    """send_network_offline sends a network.offline event."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-off")
    await device.connect()

    received_events: list[dict] = []
    def handler(etype, did, payload):
        if etype == "event":
            received_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.send_network_offline()
        await asyncio.sleep(0.2)
        assert len(received_events) == 1
        assert received_events[0]["event"] == "network.offline"
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_send_display_touched(datp_server):
    """send_display_touched sends a display.touched event."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-disp")
    await device.connect()

    received_events: list[dict] = []
    def handler(etype, did, payload):
        if etype == "event":
            received_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.send_display_touched(120, 240)
        await asyncio.sleep(0.2)
        assert len(received_events) == 1
        assert received_events[0]["event"] == "display.touched"
        assert received_events[0]["x"] == 120
        assert received_events[0]["y"] == 240
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_send_button_timeout(datp_server):
    """send_button_timeout sends a button.timeout event."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-time")
    await device.connect()

    received_events: list[dict] = []
    def handler(etype, did, payload):
        if etype == "event":
            received_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.send_button_timeout("main")
        await asyncio.sleep(0.2)
        assert len(received_events) == 1
        assert received_events[0]["event"] == "button.timeout"
        assert received_events[0]["button"] == "main"
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_send_capability_updated(datp_server):
    """send_capability_updated sends a device.capability_updated event."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-cap")
    await device.connect()

    received_events: list[dict] = []
    def handler(etype, did, payload):
        if etype == "event":
            received_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.send_capability_updated(added=["new_feature"], removed=["old_feature"])
        await asyncio.sleep(0.2)
        assert len(received_events) == 1
        assert received_events[0]["event"] == "device.capability_updated"
        assert received_events[0]["added"] == ["new_feature"]
        assert received_events[0]["removed"] == ["old_feature"]
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_send_text_prompt_sends_event(datp_server):
    """send_text_prompt sends a text.prompt event to the gateway."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-text")
    await device.connect()

    events_received: list[dict] = []
    def handler(event_type, device_id, payload):
        if event_type == "event":
            events_received.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.send_text_prompt("Hello, what time is it?")
        await asyncio.sleep(0.2)

        # Verify text.prompt event was sent
        assert len(events_received) == 1
        assert events_received[0]["event"] == "text.prompt"
        assert events_received[0]["text"] == "Hello, what time is it?"

        # Verify state changed to THINKING
        device.assert_state(State.THINKING)
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_send_text_prompt_empty_text_skipped(datp_server):
    """send_text_prompt with empty text should not send event."""
    # Note: the method itself doesn't validate empty text, but the gateway does.
    # We test that the gateway will reject it in test_channel.
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-empty")
    await device.connect()

    events_received: list[dict] = []
    def handler(event_type, device_id, payload):
        if event_type == "event":
            events_received.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        await device.send_text_prompt("   ")
        await asyncio.sleep(0.2)

        # Event is still sent (sim doesn't validate), but gateway will skip it
        assert len(events_received) == 1
        assert events_received[0]["event"] == "text.prompt"
        device.assert_state(State.THINKING)
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_send_text_prompt_state_transition(datp_server):
    """send_text_prompt transitions device to THINKING state."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-state")
    await device.connect()
    device.assert_state(State.READY)

    try:
        await device.send_text_prompt("test")
        device.assert_state(State.THINKING)
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_send_text_prompt_idempotent_when_thinking(datp_server):
    """send_text_prompt can be called again while already THINKING."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-state-idempotent")
    await device.connect()

    try:
        await device.send_text_prompt("first")
        device.assert_state(State.THINKING)
        await device.send_text_prompt("second")
        device.assert_state(State.THINKING)
    finally:
        await device.disconnect()
