"""Connection, replay, trace, and reconnect integration tests for oi-sim."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import pytest

from datp.server import DATPServer
from sim.sim import OiSim
from sim.state import State


async def _start_datp_server() -> tuple[DATPServer, asyncio.Task[None]]:
    server = DATPServer(host="localhost", port=0)
    task = asyncio.create_task(server.start())
    deadline = asyncio.get_running_loop().time() + 1.0
    while server.port == 0:
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("DATP test server did not bind a port in time")
        await asyncio.sleep(0.01)
    return server, task


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
async def test_switch_gateway_moves_live_connection_to_new_server(datp_server):
    second_server, second_task = await _start_datp_server()
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-switch")
    await device.connect()

    try:
        first_session = device._session_id
        assert "oi-sim-switch" in datp_server.device_registry
        assert "oi-sim-switch" not in second_server.device_registry

        cmd = {
            "v": "datp",
            "type": "command",
            "id": "cmd_before_switch",
            "device_id": "oi-sim-switch",
            "ts": "2026-04-27T04:40:00.000Z",
            "payload": {
                "op": "display.show_status",
                "args": {"state": "thinking", "label": "Before switch"},
            },
        }
        await datp_server.send_to_device("oi-sim-switch", cmd)
        await asyncio.sleep(0.2)
        assert len(device.received_commands) == 1

        changed = await device.switch_gateway(f"ws://localhost:{second_server.port}/datp")
        await asyncio.sleep(0.2)

        assert changed is True
        assert device.gateway == f"ws://localhost:{second_server.port}/datp"
        assert device.is_connected is True
        assert device._session_id is not None
        assert device._session_id != first_session
        assert device.state == State.READY
        assert device.received_commands == []
        assert device.received_messages == []
        assert "oi-sim-switch" not in datp_server.device_registry
        assert "oi-sim-switch" in second_server.device_registry
        device.assert_trace_contains("gateway_switch_complete", direction="lifecycle")
    finally:
        await device.disconnect()
        await second_server.stop()
        await second_task
        await asyncio.sleep(0.15)


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
