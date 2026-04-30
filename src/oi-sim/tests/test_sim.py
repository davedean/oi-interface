"""Tests for oi-sim — the virtual DATP device."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
import pytest
import websockets

from datp.server import DATPServer

from sim.state import InvalidTransition, State, StateMachine
from sim.sim import OiSim
from sim.fixtures import load_fixture


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
async def datp_server():
    """Start the DATP server, yield it, then stop it."""
    srv = DATPServer(host="localhost", port=0)
    task = asyncio.create_task(srv.start())
    await asyncio.sleep(0.15)  # allow bind to complete
    yield srv
    await srv.stop()
    await asyncio.sleep(0.15)


@pytest.fixture
async def sim(datp_server):
    """Connected OiSim instance (Yields → disconnects automatically)."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-test")
    await device.connect()
    yield device
    await device.disconnect()


# ------------------------------------------------------------------
# StateMachine unit tests
# ------------------------------------------------------------------

class TestStateMachine:
    def test_initial_state(self):
        sm = StateMachine()
        assert sm.state == State.READY

    def test_initial_state_custom(self):
        sm = StateMachine(State.BOOTING)
        assert sm.state == State.BOOTING

    def test_valid_transition(self):
        sm = StateMachine(State.READY)
        sm.transition(State.RECORDING)
        assert sm.state == State.RECORDING

    def test_invalid_transition_raises(self):
        sm = StateMachine(State.READY)
        with pytest.raises(InvalidTransition) as exc_info:
            sm.transition(State.PLAYING)
        assert exc_info.value.from_state == State.READY
        assert exc_info.value.to_state == State.PLAYING

    def test_any_state_to_error(self):
        sm = StateMachine(State.RECORDING)
        sm.transition(State.ERROR)
        assert sm.state == State.ERROR

    def test_any_state_to_safe_mode(self):
        sm = StateMachine(State.THINKING)
        sm.transition(State.SAFE_MODE)
        assert sm.state == State.SAFE_MODE

    def test_booting_to_ready_or_offline(self):
        sm = StateMachine(State.BOOTING)
        sm.transition(State.READY)
        assert sm.state == State.READY

    def test_booting_to_pairing(self):
        """BOOTING → PAIRING is a valid transition (spec §5.1)."""
        sm = StateMachine(State.BOOTING)
        sm.transition(State.PAIRING)
        assert sm.state == State.PAIRING
        sm2 = StateMachine(State.BOOTING)
        sm2.transition(State.OFFLINE)
        assert sm2.state == State.OFFLINE

    def test_recording_to_uploading_or_ready(self):
        sm = StateMachine(State.RECORDING)
        sm.transition(State.UPLOADING)
        assert sm.state == State.UPLOADING
        sm2 = StateMachine(State.RECORDING)
        sm2.transition(State.READY)
        assert sm2.state == State.READY

    def test_uploading_to_thinking(self):
        sm = StateMachine(State.UPLOADING)
        sm.transition(State.THINKING)
        assert sm.state == State.THINKING

    def test_thinking_to_response_cached(self):
        sm = StateMachine(State.THINKING)
        sm.transition(State.RESPONSE_CACHED)
        assert sm.state == State.RESPONSE_CACHED

    def test_response_cached_to_playing(self):
        sm = StateMachine(State.RESPONSE_CACHED)
        sm.transition(State.PLAYING)
        assert sm.state == State.PLAYING
    
    def test_response_cached_to_thinking(self):
        sm = StateMachine(State.RESPONSE_CACHED)
        sm.transition(State.THINKING)
        assert sm.state == State.THINKING

    def test_playing_to_ready(self):
        sm = StateMachine(State.PLAYING)
        sm.transition(State.READY)
        assert sm.state == State.READY

    def test_assert_state_passes(self):
        sm = StateMachine(State.READY)
        sm.assert_state(State.READY)

    def test_assert_state_fails(self):
        sm = StateMachine(State.READY)
        with pytest.raises(AssertionError):
            sm.assert_state(State.RECORDING)

    def test_receive_command_no_change(self):
        sm = StateMachine(State.READY)
        result = sm.receive_command("display.show_status")
        assert result == State.READY

    def test_receive_command_audio_play_transitions(self):
        sm = StateMachine(State.RESPONSE_CACHED)
        result = sm.receive_command("audio.play")
        assert result == State.PLAYING
        assert sm.state == State.PLAYING

    def test_receive_command_audio_stop_to_ready(self):
        sm = StateMachine(State.PLAYING)
        result = sm.receive_command("audio.stop")
        assert result == State.READY

    def test_receive_command_mute_until(self):
        sm = StateMachine(State.READY)
        result = sm.receive_command("device.mute_until")
        assert result == State.MUTED

    def test_receive_command_display_show_card_transitions_from_thinking(self):
        sm = StateMachine(State.THINKING)
        result = sm.receive_command("display.show_card", {"title": "Response"})
        assert result == State.RESPONSE_CACHED
        assert sm.state == State.RESPONSE_CACHED

    def test_receive_command_display_text_delta_stays_in_thinking(self):
        """display.show_text_delta with is_final=False stays in current state."""
        sm = StateMachine(State.THINKING)
        result = sm.receive_command("display.show_text_delta", {"text_delta": "Hello", "is_final": False})
        assert result == State.THINKING
        assert sm.state == State.THINKING

    def test_receive_command_display_text_delta_final_transitions(self):
        """display.show_text_delta with is_final=True transitions to RESPONSE_CACHED."""
        sm = StateMachine(State.THINKING)
        result = sm.receive_command("display.show_text_delta", {"text_delta": "Hello", "is_final": True})
        assert result == State.RESPONSE_CACHED
        assert sm.state == State.RESPONSE_CACHED

    def test_receive_command_audio_play_idempotent(self):
        """audio.play from PLAYING is idempotent (no-op, not an error)."""
        sm = StateMachine(State.PLAYING)
        result = sm.receive_command("audio.play")
        assert result == State.PLAYING  # stayed in PLAYING, did not raise

    def test_receive_command_audio_stop_idempotent(self):
        """audio.stop from READY is idempotent (no-op, not an error)."""
        sm = StateMachine(State.READY)
        result = sm.receive_command("audio.stop")
        assert result == State.READY  # stayed in READY, did not raise


# ------------------------------------------------------------------
# Integration tests — oi-sim ↔ DATPServer
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_and_hello(datp_server):
    """Connect, send hello, receive hello_ack, state=READY."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-001")
    await device.connect()

    try:
        assert device.state == State.READY
        assert device._session_id is not None
        assert "oi-sim-001" in datp_server.device_registry
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_long_hold_and_release(datp_server):
    """long_hold_started → RECORDING; release → UPLOADING."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-002")
    await device.connect()

    try:
        # Simulate long hold
        await device.press_long_hold()
        assert device.state == State.RECORDING

        # Release → upload
        await device.release()
        assert device.state == State.UPLOADING
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_double_tap(datp_server):
    """double_tap → PLAYING (from RESPONSE_CACHED)."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-003")
    await device.connect()

    try:
        # Walk the correct path: READY → RECORDING → UPLOADING → THINKING → RESPONSE_CACHED
        await device.press_long_hold()
        assert device.state == State.RECORDING
        await device.release()
        assert device.state == State.UPLOADING
        device._state_machine.transition(State.THINKING)
        assert device.state == State.THINKING
        device._state_machine.transition(State.RESPONSE_CACHED)
        assert device.state == State.RESPONSE_CACHED

        # Now double_tap
        await device.double_tap()
        assert device.state == State.PLAYING
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_upload_audio(datp_server):
    """Upload a WAV file as audio chunks; assert recording_finished sent."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-004")
    await device.connect()

    # Subscribe BEFORE sending chunks — audio is sent synchronously.
    audio_events: list[dict] = []
    def handler(event_type, device_id, payload):
        if event_type in ("audio_chunk", "event"):
            audio_events.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(b"RIFF" + b"\x00" * 100)  # minimal WAV header stub
            tmp_path = tmp.name

        await device.press_long_hold()
        stream_id = await device.upload_audio_file(tmp_path)
        assert stream_id.startswith("rec_")
        await asyncio.sleep(0.1)  # let async send loop drain

        # Chunks must have arrived at the gateway before we unsubscribe.
        # audio_events includes both audio_chunk payloads and event payloads;
        # verify at least the audio_chunk entries have stream_id.
        chunk_events = [e for e in audio_events if "stream_id" in e]
        assert len(chunk_events) > 0, f"Expected audio_chunk events, got {audio_events!r}"
        assert all(e["stream_id"].startswith("rec_") for e in chunk_events)

        os.unlink(tmp_path)
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()


@pytest.mark.asyncio
async def test_command_received(datp_server):
    """Server sends display.show_status; sim records it."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-005")
    await device.connect()

    try:
        # Server sends a command to the device.
        cmd = {
            "v": "datp",
            "type": "command",
            "id": "cmd_test_001",
            "device_id": "oi-sim-005",
            "ts": "2026-04-27T04:40:00.000Z",
            "payload": {
                "op": "display.show_status",
                "args": {"state": "thinking", "label": "Checking repo"},
            },
        }
        ok = await datp_server.send_to_device("oi-sim-005", cmd)
        assert ok is True

        # Wait for the device to receive and process it.
        await asyncio.sleep(0.3)

        device.assert_command_received("display.show_status")
        assert device.received_commands[-1]["args"]["state"] == "thinking"
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_command_not_received_initially(datp_server):
    """No commands received before any are sent."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-006")
    await device.connect()

    try:
        device.assert_command_not_received("display.show_status")
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_mute_until_command_transitions_state(datp_server):
    """device.mute_until command advances sim to MUTED state."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-007")
    await device.connect()

    try:
        device.assert_state(State.READY)

        cmd = {
            "v": "datp",
            "type": "command",
            "id": "cmd_mute",
            "device_id": "oi-sim-007",
            "ts": "2026-04-27T04:40:00.000Z",
            "payload": {
                "op": "device.mute_until",
                "args": {"until": "2026-04-27T15:30:00Z"},
            },
        }
        await datp_server.send_to_device("oi-sim-007", cmd)
        await asyncio.sleep(0.3)

        device.assert_state(State.MUTED)
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_disconnect_cleanup(datp_server):
    """Disconnect, verify connection closed and device removed from registry."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-008")
    await device.connect()

    assert "oi-sim-008" in datp_server.device_registry

    await device.disconnect()
    await asyncio.sleep(0.2)

    assert "oi-sim-008" not in datp_server.device_registry


@pytest.mark.asyncio
async def test_double_connect_raises(datp_server):
    """Calling connect() twice raises RuntimeError."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-009")
    await device.connect()
    try:
        with pytest.raises(RuntimeError, match="Already connected"):
            await device.connect()
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_hello_includes_capabilities(datp_server):
    """Hello payload includes the advertised capabilities."""
    custom_caps = {"input": ["hold_to_record"], "output": [], "sensors": []}
    device = OiSim(
        gateway=f"ws://localhost:{datp_server.port}/datp",
        device_id="oi-sim-cap",
        capabilities=custom_caps,
    )
    await device.connect()
    try:
        entry = datp_server.device_registry["oi-sim-cap"]
        assert entry["capabilities"] == custom_caps
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_received_messages_property(datp_server):
    """received_messages accumulates all incoming messages."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-msgs")
    await device.connect()

    try:
        # Send a command from server
        cmd = {
            "v": "datp", "type": "command", "id": "cmd_msg_01",
            "device_id": "oi-sim-msgs", "ts": "2026-04-27T04:40:00.000Z",
            "payload": {"op": "display.show_card", "args": {}},
        }
        await datp_server.send_to_device("oi-sim-msgs", cmd)
        await asyncio.sleep(0.2)

        received = device.received_messages
        assert len(received) >= 1
        assert any(m.get("payload", {}).get("op") == "display.show_card" for m in received)
    finally:
        await device.disconnect()


# ------------------------------------------------------------------
# Fixtures module tests
# ------------------------------------------------------------------

class TestFixtures:
    def test_load_fixture_valid(self, tmp_path):
        """load_fixture parses a valid JSONL file."""
        fixture = tmp_path / "test.jsonl"
        fixture.write_text(
            '{"type":"command","payload":{"op":"display.show_status"}}\n'
            '{"type":"command","payload":{"op":"audio.play"}}\n'
        )
        result = load_fixture(str(fixture))
        assert len(result) == 2
        assert result[0]["payload"]["op"] == "display.show_status"

    def test_load_fixture_missing_file(self):
        """FileNotFoundError for missing fixture."""
        with pytest.raises(FileNotFoundError):
            load_fixture("/no/such/file.jsonl")

    def test_load_fixture_invalid_json(self, tmp_path):
        """ValueError for non-JSON lines."""
        fixture = tmp_path / "bad.jsonl"
        fixture.write_text('{"type":"ok"}\nnot json at all\n')
        with pytest.raises(ValueError, match="Invalid JSON"):
            load_fixture(str(fixture))


# ------------------------------------------------------------------
# OiSim assertions
# ------------------------------------------------------------------

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
# New event type tests
# ------------------------------------------------------------------

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


# ------------------------------------------------------------------
# New command response tests
# ------------------------------------------------------------------

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


# ------------------------------------------------------------------
# StateMachine new properties tests
# ------------------------------------------------------------------

class TestStateMachineNewProperties:
    def test_volume_property_default(self):
        """StateMachine has default volume of 80."""
        sm = StateMachine()
        assert sm.volume == 80

    def test_volume_property_updated(self):
        """StateMachine volume can be updated via command."""
        sm = StateMachine()
        sm.receive_command("device.set_volume", {"level": 60})
        assert sm.volume == 60

    def test_led_enabled_property_default(self):
        """StateMachine has LED enabled by default."""
        sm = StateMachine()
        assert sm.led_enabled is True

    def test_led_enabled_property_updated(self):
        """StateMachine LED can be toggled via command."""
        sm = StateMachine()
        sm.receive_command("device.set_led", {"enabled": False})
        assert sm.led_enabled is False

    def test_brightness_property_default(self):
        """StateMachine has default brightness of 100."""
        sm = StateMachine()
        assert sm.brightness == 100

    def test_brightness_property_updated(self):
        """StateMachine brightness can be updated via command."""
        sm = StateMachine()
        sm.receive_command("device.set_brightness", {"value": 75})
        assert sm.brightness == 75


# ------------------------------------------------------------------
# Tests: Text input feature (send_text_prompt)
# ------------------------------------------------------------------

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


@pytest.mark.asyncio
async def test_reconnect_resets_session_and_local_buffers(datp_server):
    """Reconnect should create a new session and clear per-session local buffers."""
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-reconnect")
    await device.connect()

    try:
        first_session = device._session_id
        assert first_session is not None

        cmd = {
            "v": "datp",
            "type": "command",
            "id": "cmd_reconnect_001",
            "device_id": "oi-sim-reconnect",
            "ts": "2026-04-27T04:40:00.000Z",
            "payload": {
                "op": "display.show_status",
                "args": {"state": "thinking", "label": "Before reconnect"},
            },
        }
        await datp_server.send_to_device("oi-sim-reconnect", cmd)
        await asyncio.sleep(0.2)
        assert len(device.received_commands) == 1
        assert len(device.received_messages) >= 1

        await device.reconnect()

        assert device.is_connected is True
        assert device._session_id is not None
        assert device._session_id != first_session
        assert device.received_commands == []
        assert device.received_messages == []
        device.assert_trace_contains("reconnect_wait", direction="lifecycle")
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_strict_mode_raises_on_invalid_command_transition(datp_server):
    """Strict mode should fail when a command implies an invalid state transition."""
    device = OiSim(
        gateway=f"ws://localhost:{datp_server.port}/datp",
        device_id="oi-sim-strict",
        strict=True,
    )
    await device.connect()

    try:
        cmd = {
            "v": "datp",
            "type": "command",
            "id": "cmd_invalid_transition",
            "device_id": "oi-sim-strict",
            "ts": "2026-04-27T04:40:00.000Z",
            "payload": {
                "op": "audio.play",
                "args": {},
            },
        }
        await datp_server.send_to_device("oi-sim-strict", cmd)
        await asyncio.sleep(0.2)

        assert device.is_connected is False
        assert any(event.kind == "command" and event.direction == "recv" for event in device.trace_events)
    finally:
        await device.disconnect()


@pytest.mark.asyncio
async def test_trace_output_writes_jsonl(datp_server, tmp_path: Path):
    """Trace mode should write JSONL entries for lifecycle, send, and recv activity."""
    trace_path = tmp_path / "oi-sim-trace.jsonl"
    device = OiSim(
        gateway=f"ws://localhost:{datp_server.port}/datp",
        device_id="oi-sim-trace",
        trace_path=trace_path,
    )
    await device.connect()

    try:
        await device.send_text_prompt("hello trace")
        cmd = {
            "v": "datp",
            "type": "command",
            "id": "cmd_trace_001",
            "device_id": "oi-sim-trace",
            "ts": "2026-04-27T04:40:00.000Z",
            "payload": {
                "op": "display.show_card",
                "args": {"title": "Response", "body": "hi"},
            },
        }
        await datp_server.send_to_device("oi-sim-trace", cmd)
        await asyncio.sleep(0.2)
    finally:
        await device.disconnect()

    lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines, "expected trace file to contain events"
    parsed = [json.loads(line) for line in lines]
    assert any(entry["direction"] == "send" and entry["kind"] == "event" for entry in parsed)
    assert any(entry["direction"] == "recv" and entry["kind"] == "command" for entry in parsed)
    assert any(entry["direction"] == "lifecycle" and entry["kind"] == "disconnect_complete" for entry in parsed)


@pytest.mark.asyncio
async def test_text_prompt_event_flow_without_agent_response(datp_server):
    """Text prompts reach the gateway and leave the device in THINKING.

    This test verifies only the device->gateway event flow; it does not mock
    an agent response back to the device.
    """
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-roundtrip")
    await device.connect()

    commands_received: list[dict] = []
    def handler(event_type, device_id, payload):
        if event_type == "event" and payload.get("event") == "text.prompt":
            pass  # text prompt sent
        elif event_type == "command":
            commands_received.append(payload)

    datp_server.event_bus.subscribe(handler)
    try:
        # Send text prompt
        await device.send_text_prompt("what is 2+2?")
        await asyncio.sleep(0.2)

        # Device should be in THINKING state
        device.assert_state(State.THINKING)

        # No agent backend is mocked here, so no response command should arrive.
        text_events = [e for e in commands_received if e.get("op") == "display.show_card"]
        assert text_events == []
    finally:
        datp_server.event_bus.unsubscribe(handler)
        await device.disconnect()
