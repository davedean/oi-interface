"""Tests for the DATP WebSocket server."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
import websockets

from datp.messages import UNKNOWN_DEVICE, build_ack, build_command, build_error, build_hello_ack, parse_message


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def make_hello(device_id: str, hello_id: str = "msg_hello") -> dict[str, Any]:
    return {
        "v": "datp",
        "type": "hello",
        "id": hello_id,
        "device_id": device_id,
        "ts": "2026-04-27T04:40:00.000Z",
        "payload": {
            "device_type": "test-device",
            "protocol": "datp",
            "firmware": "test-fw/1.0.0",
            "capabilities": {
                "audio_in": True,
                "audio_out": True,
                "display": "test_display",
                "buttons": ["test_button"]
            },
            "state": {
                "mode": "READY",
                "battery_percent": 100,
                "wifi_rssi": -50
            },
            "resume_token": None,
            "nonce": "abc123",
        },
    }


def make_event(device_id: str) -> dict[str, Any]:
    return {
        "v": "datp",
        "type": "event",
        "id": "evt_001",
        "device_id": device_id,
        "ts": "2026-04-27T04:40:01.000Z",
        "payload": {"event": "button.long_hold_started", "button": "main"},
    }


def make_audio_chunk(device_id: str) -> dict[str, Any]:
    return {
        "v": "datp",
        "type": "audio_chunk",
        "id": "aud_001",
        "device_id": device_id,
        "ts": "2026-04-27T04:40:02.000Z",
        "payload": {
            "stream_id": "rec_1",
            "seq": 0,
            "format": "pcm16",
            "sample_rate": 16000,
            "channels": 1,
            "data_b64": "AAAA",
        },
    }


def make_state(device_id: str) -> dict[str, Any]:
    return {
        "v": "datp",
        "type": "state",
        "id": "state_001",
        "device_id": device_id,
        "ts": "2026-04-27T04:40:03.000Z",
        "payload": {
            "mode": "READY",
            "battery_percent": 71,
            "charging": False,
            "wifi_rssi": -67,
            "heap_free": 132120,
            "uptime_s": 9231,
            "audio_cache_used_bytes": 580222,
            "muted_until": None,
        },
    }


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
async def server():
    """Start the DATP server on an ephemeral port, yield it, then stop it."""
    from datp.server import DATPServer
    srv = DATPServer(host="localhost", port=0)
    await srv.start()
    yield srv
    await srv.stop()
    await asyncio.sleep(0.05)


# ------------------------------------------------------------------
# Integration tests
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hello_handshake(server):
    """Connect, send hello, receive hello_ack with correct fields."""
    async with websockets.connect(f"ws://localhost:{server.port}/datp") as ws:
        await ws.send(json.dumps(make_hello("test-device-001")))
        resp_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        resp: dict[str, Any] = json.loads(resp_raw)

        assert "test-device-001" in server.device_registry
        assert resp["type"] == "hello_ack"
        assert resp["v"] == "datp"
        assert "id" in resp
        assert resp["device_id"] == "test-device-001"
        payload = resp["payload"]
        assert "session_id" in payload
        assert "server_time" in payload
        assert payload["accepted_protocol"] == "datp"
        assert "send_capabilities" in payload


@pytest.mark.asyncio
async def test_hello_handshake_includes_conversation_preferences(server):
    hello = make_hello("test-device-conversation")
    hello["payload"]["conversation"] = {
        "backend_id": "codex",
        "agent_id": "build",
        "session_key": "oi:session:test123",
    }
    server.available_backends = [{"id": "pi", "name": "Pi"}, {"id": "codex", "name": "Codex"}]
    server.default_backend_id = "pi"
    server.default_agent = {"id": "main", "name": "Main"}
    server.available_agents = [server.default_agent, {"id": "build", "name": "Build"}]

    async with websockets.connect(f"ws://localhost:{server.port}/datp") as ws:
        await ws.send(json.dumps(hello))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        payload = resp["payload"]
        assert payload["selected_backend"] == "codex"
        assert payload["selected_agent"]["id"] == "build"
        assert payload["selected_session_key"] == "oi:session:test123"
        assert server.get_device_conversation("test-device-conversation") == {
            "backend_id": "codex",
            "agent_id": "build",
            "session_key": "oi:session:test123",
        }


@pytest.mark.asyncio
async def test_conversation_update_event_switches_backend_and_session_without_reconnect(server):
    server.available_backends = [{"id": "pi", "name": "Pi"}, {"id": "codex", "name": "Codex"}]
    server.default_backend_id = "pi"
    server.default_agent = {"id": "main", "name": "Main"}
    server.available_agents = [server.default_agent, {"id": "build", "name": "Build"}]

    async with websockets.connect(f"ws://localhost:{server.port}/datp") as ws:
        await ws.send(json.dumps(make_hello("switch-device")))
        hello_ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        session_id = hello_ack["payload"]["session_id"]

        await ws.send(json.dumps({
            "v": "datp",
            "type": "event",
            "id": "evt_switch_1",
            "device_id": "switch-device",
            "ts": "2026-04-27T04:41:00.000Z",
            "payload": {
                "event": "conversation.update",
                "conversation": {
                    "backend_id": "codex",
                    "agent_id": "build",
                    "session_key": "oi:session:switched",
                },
            },
        }))

        update_ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        assert update_ack["type"] == "hello_ack"
        assert update_ack["payload"]["session_id"] == session_id
        assert update_ack["payload"]["selected_backend"] == "codex"
        assert update_ack["payload"]["selected_agent"]["id"] == "build"
        assert update_ack["payload"]["selected_session_key"] == "oi:session:switched"
        assert server.get_device_conversation("switch-device") == {
            "backend_id": "codex",
            "agent_id": "build",
            "session_key": "oi:session:switched",
        }


@pytest.mark.asyncio
async def test_device_conversation_updates_are_isolated_per_device(server):
    server.available_backends = [{"id": "pi", "name": "Pi"}, {"id": "codex", "name": "Codex"}]
    server.default_backend_id = "pi"
    server.default_agent = {"id": "main", "name": "Main"}
    server.available_agents = [server.default_agent, {"id": "build", "name": "Build"}]

    async with websockets.connect(f"ws://localhost:{server.port}/datp") as ws_a, websockets.connect(f"ws://localhost:{server.port}/datp") as ws_b:
        await ws_a.send(json.dumps(make_hello("device-a")))
        await ws_b.send(json.dumps(make_hello("device-b")))
        await asyncio.wait_for(ws_a.recv(), timeout=5.0)
        await asyncio.wait_for(ws_b.recv(), timeout=5.0)

        await ws_b.send(json.dumps({
            "v": "datp",
            "type": "event",
            "id": "evt_switch_b",
            "device_id": "device-b",
            "ts": "2026-04-27T04:42:00.000Z",
            "payload": {
                "event": "conversation.update",
                "conversation": {
                    "backend_id": "codex",
                    "agent_id": "build",
                    "session_key": "oi:session:b",
                },
            },
        }))
        await asyncio.wait_for(ws_b.recv(), timeout=5.0)

        assert server.get_device_conversation("device-a") == {
            "backend_id": "pi",
            "agent_id": "main",
            "session_key": "oi:device:device-a",
        }
        assert server.get_device_conversation("device-b") == {
            "backend_id": "codex",
            "agent_id": "build",
            "session_key": "oi:session:b",
        }


@pytest.mark.asyncio
async def test_event_emit(server):
    """Connect, subscribe to event bus, send an event, assert callback was called."""
    received: list[tuple[str, str, dict]] = []

    def handler(event_type: str, device_id: str, payload: dict):
        received.append((event_type, device_id, payload))

    server.event_bus.subscribe(handler)
    try:
        async with websockets.connect(f"ws://localhost:{server.port}/datp") as ws:
            await ws.send(json.dumps(make_hello("test-device-001")))
            await asyncio.wait_for(ws.recv(), timeout=5.0)
            await ws.send(json.dumps(make_event("test-device-001")))
            await asyncio.sleep(0.2)

        assert len(received) == 1
        event_type, device_id, payload = received[0]
        assert event_type == "event"
        assert device_id == "test-device-001"
        assert payload["event"] == "button.long_hold_started"
    finally:
        server.event_bus.unsubscribe(handler)


@pytest.mark.asyncio
async def test_audio_chunk_emit(server):
    """audio_chunk message is emitted on the event bus."""
    received: list[tuple[str, str, dict]] = []

    def handler(event_type: str, device_id: str, payload: dict):
        received.append((event_type, device_id, payload))

    server.event_bus.subscribe(handler)
    try:
        async with websockets.connect(f"ws://localhost:{server.port}/datp") as ws:
            await ws.send(json.dumps(make_hello("test-device-001")))
            await asyncio.wait_for(ws.recv(), timeout=5.0)
            await ws.send(json.dumps(make_audio_chunk("test-device-001")))
            await asyncio.sleep(0.2)

        assert len(received) == 1
        event_type, device_id, payload = received[0]
        assert event_type == "audio_chunk"
        assert payload["stream_id"] == "rec_1"
    finally:
        server.event_bus.unsubscribe(handler)


@pytest.mark.asyncio
async def test_state_emit(server):
    """state message is emitted on the event bus."""
    received: list[tuple[str, str, dict]] = []

    def handler(event_type: str, device_id: str, payload: dict):
        received.append((event_type, device_id, payload))

    server.event_bus.subscribe(handler)
    try:
        async with websockets.connect(f"ws://localhost:{server.port}/datp") as ws:
            await ws.send(json.dumps(make_hello("test-device-001")))
            await asyncio.wait_for(ws.recv(), timeout=5.0)
            await ws.send(json.dumps(make_state("test-device-001")))
            await asyncio.sleep(0.2)

        assert len(received) == 1
        event_type, device_id, payload = received[0]
        assert event_type == "state"
        assert payload["mode"] == "READY"
    finally:
        server.event_bus.unsubscribe(handler)


@pytest.mark.asyncio
async def test_device_registry(server):
    """Connect two devices, verify both tracked; after disconnect both removed."""
    registry = server.device_registry

    async with websockets.connect(f"ws://localhost:{server.port}/datp") as ws_a:
        await ws_a.send(json.dumps(make_hello("test-device-a")))
        resp = json.loads(await asyncio.wait_for(ws_a.recv(), timeout=5.0))
        assert resp["type"] == "hello_ack"
        assert "test-device-a" in registry

    await asyncio.sleep(0.1)
    assert "test-device-a" not in registry

    async with websockets.connect(f"ws://localhost:{server.port}/datp") as ws_b:
        await ws_b.send(json.dumps(make_hello("test-device-b")))
        resp = json.loads(await asyncio.wait_for(ws_b.recv(), timeout=5.0))
        assert resp["type"] == "hello_ack"
        assert "test-device-b" in registry

    await asyncio.sleep(0.1)
    assert "test-device-b" not in registry


@pytest.mark.asyncio
async def test_invalid_envelope(server):
    """Send malformed JSON, assert error response."""
    async with websockets.connect(f"ws://localhost:{server.port}/datp") as ws:
        await ws.send("not valid json at all!!!")
        resp_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        resp: dict[str, Any] = json.loads(resp_raw)
        assert resp["type"] == "error"
        assert resp["payload"]["code"] == "INVALID_JSON"
        assert resp["payload"]["related_id"] is None


@pytest.mark.asyncio
async def test_disconnect_cleanup(server):
    """Connect, disconnect, verify device removed from registry."""
    device_id = "test-device-disconnect"

    async with websockets.connect(f"ws://localhost:{server.port}/datp") as ws:
        await ws.send(json.dumps(make_hello(device_id)))
        await asyncio.wait_for(ws.recv(), timeout=5.0)

    await asyncio.sleep(0.3)
    assert device_id not in server.device_registry


@pytest.mark.asyncio
async def test_send_to_device(server):
    """send_to_device delivers a message to the correct WebSocket."""
    device_id = "send-test-device"

    async with websockets.connect(f"ws://localhost:{server.port}/datp") as ws:
        await ws.send(json.dumps(make_hello(device_id)))
        await asyncio.wait_for(ws.recv(), timeout=5.0)  # consume hello_ack

        ok = await server.send_to_device(
            device_id,
            {
                "v": "datp",
                "type": "command",
                "id": "cmd_out",
                "device_id": device_id,
                "ts": "2026-04-27T04:40:00.000Z",
                "payload": {"op": "display.show_status", "args": {}},
            },
        )
        assert ok is True
        # Receive the outbound command on the client socket.
        resp_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)

    assert "cmd_out" in resp_raw


@pytest.mark.asyncio
async def test_send_to_device_not_connected(server):
    """send_to_device returns False when the device is not in the registry."""
    ok = await server.send_to_device(
        "no-such-device",
        {"v": "datp", "type": "command", "id": "cmd_001", "device_id": "*", "ts": "2026-04-27T04:40:00.000Z", "payload": {}},
    )
    assert ok is False


@pytest.mark.asyncio
async def test_send_to_device_missing_fields(server):
    """send_to_device returns False when the envelope is missing required fields."""
    async with websockets.connect(f"ws://localhost:{server.port}/datp") as ws:
        await ws.send(json.dumps(make_hello("test-device")))
        await asyncio.wait_for(ws.recv(), timeout=5.0)

        # Missing 'v' and 'id' — should return False without crashing.
        ok = await server.send_to_device("test-device", {"type": "command"})
        assert ok is False


@pytest.mark.asyncio
async def test_duplicate_hello_disconnects_old(server):
    """A second hello from the same device_id closes the old connection."""
    # First connection with device_id
    ws1 = await websockets.connect(f"ws://localhost:{server.port}/datp")
    await ws1.send(json.dumps(make_hello("dup-device", hello_id="hello_1")))
    resp1 = json.loads(await asyncio.wait_for(ws1.recv(), timeout=5.0))
    assert resp1["type"] == "hello_ack"
    assert "dup-device" in server.device_registry

    # Second connection with same device_id should close the first.
    ws2 = await websockets.connect(f"ws://localhost:{server.port}/datp")
    await ws2.send(json.dumps(make_hello("dup-device", hello_id="hello_2")))
    resp2 = json.loads(await asyncio.wait_for(ws2.recv(), timeout=5.0))
    assert resp2["type"] == "hello_ack"
    assert "dup-device" in server.device_registry

    # First connection should have been closed by the server.
    # Sending on ws1 should raise ConnectionClosed.
    with pytest.raises(websockets.ConnectionClosed):
        await ws1.send(json.dumps(make_event("dup-device")))

    await ws2.close()


@pytest.mark.asyncio
async def test_device_sent_command_returns_error(server):
    """A device sending a 'command' to the server gets an error reply.

    Per DATP, commands flow gateway->device only. The server must not
    acknowledge commands received from a device.
    """
    async with websockets.connect(f"ws://localhost:{server.port}/datp") as ws:
        await ws.send(json.dumps(make_hello("cmd-test-device")))
        await asyncio.wait_for(ws.recv(), timeout=5.0)

        # Device tries to send a command to the server.
        bad_cmd = {
            "v": "datp",
            "type": "command",
            "id": "device_cmd_001",
            "device_id": "cmd-test-device",
            "ts": "2026-04-27T04:40:02.000Z",
            "payload": {"op": "display.show_status", "args": {}},
        }
        await ws.send(json.dumps(bad_cmd))
        resp_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        resp = json.loads(resp_raw)

        assert resp["type"] == "error"
        assert resp["payload"]["code"] == "INVALID_MESSAGE_DIRECTION"
        assert "gateway" in resp["payload"]["message"]


# ------------------------------------------------------------------
# Unit tests — messages module
# ------------------------------------------------------------------

def test_parse_message_valid():
    msg = parse_message(
        '{"v":"datp","type":"event","id":"evt_1","device_id":"d1",'
        '"ts":"2026-04-27T04:40:00.000Z","payload":{}}'
    )
    assert msg["v"] == "datp"
    assert msg["type"] == "event"
    assert msg["id"] == "evt_1"
    assert msg["device_id"] == "d1"


def test_parse_message_invalid_json():
    with pytest.raises(ValueError, match="Invalid JSON"):
        parse_message("not json")


def test_parse_message_missing_version():
    with pytest.raises(ValueError, match="version.*required"):
        parse_message(
            '{"type":"event","id":"x","device_id":"d",'
            '"ts":"2026-04-27T04:40:00.000Z","payload":{}}'
        )


def test_parse_message_wrong_version():
    with pytest.raises(ValueError, match="version"):
        parse_message(
            '{"v":"other","type":"event","id":"x","device_id":"d",'
            '"ts":"2026-04-27T04:40:00.000Z","payload":{}}'
        )


def test_parse_message_missing_ts():
    with pytest.raises(ValueError, match="Missing required field: ts"):
        parse_message(
            '{"v":"datp","type":"event","id":"x","device_id":"d","payload":{}}'
        )


def test_parse_message_missing_device_id():
    with pytest.raises(ValueError, match="Missing required field: device_id"):
        parse_message(
            '{"v":"datp","type":"event","id":"x",'
            '"ts":"2026-04-27T04:40:00.000Z","payload":{}}'
        )


def test_parse_message_invalid_ts_format():
    with pytest.raises(ValueError, match="Invalid timestamp format"):
        parse_message(
            '{"v":"datp","type":"event","id":"x","device_id":"d",'
            '"ts":"not-a-timestamp","payload":{}}'
        )


def test_build_hello_ack():
    ack = build_hello_ack(session_id="sess_123", device_id="my-device")
    assert ack["v"] == "datp"
    assert ack["type"] == "hello_ack"
    assert ack["device_id"] == "my-device"
    payload = ack["payload"]
    assert payload["session_id"] == "sess_123"
    assert payload["server_time"]
    assert payload["accepted_protocol"] == "datp"


def test_build_ack():
    ack = build_ack("cmd_001", ok=True)
    assert ack["type"] == "ack"
    assert ack["device_id"] == UNKNOWN_DEVICE
    assert ack["payload"]["command_id"] == "cmd_001"
    assert ack["payload"]["ok"] is True


def test_build_error():
    err = build_error(
        "device_x", "INVALID_TRANSITION", "Cannot do that", related_id="cmd_5"
    )
    assert err["type"] == "error"
    assert err["device_id"] == "device_x"
    assert err["payload"]["code"] == "INVALID_TRANSITION"
    assert err["payload"]["message"] == "Cannot do that"
    assert err["payload"]["related_id"] == "cmd_5"


def test_build_error_no_related_id():
    err = build_error("d", "FOO", "msg")
    assert err["payload"]["related_id"] is None


def test_build_command():
    cmd = build_command("stick-001", "display.show_status", {"state": "thinking"})
    assert cmd["v"] == "datp"
    assert cmd["type"] == "command"
    assert cmd["device_id"] == "stick-001"
    assert cmd["payload"]["op"] == "display.show_status"
    assert cmd["payload"]["args"] == {"state": "thinking"}
    assert cmd["id"].startswith("cmd_")


def test_build_command_with_id():
    cmd = build_command("d", "audio.play", None, command_id="cmd_abc123")
    assert cmd["id"] == "cmd_abc123"
    assert cmd["payload"]["args"] == {}


def test_event_bus_isolates_subscriber_exceptions():
    """A failing subscriber must not prevent other subscribers from receiving events."""
    from datp.events import EventBus

    bus = EventBus()
    received: list[str] = []

    def bad_subscriber(event_type, device_id, payload):
        raise RuntimeError("intentional failure")

    def good_subscriber(event_type, device_id, payload):
        received.append(event_type)

    bus.subscribe(bad_subscriber)
    bus.subscribe(good_subscriber)

    # Emit should not raise; good_subscriber should still be called.
    bus.emit("test_event", "dev1", {})

    assert received == ["test_event"]
