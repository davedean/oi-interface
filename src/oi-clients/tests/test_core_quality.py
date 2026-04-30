from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


client_src = Path(__file__).parent.parent / "generic_sbc_handheld"
if str(client_src) not in sys.path:
    sys.path.insert(0, str(client_src))

from oi_client.capabilities import RuntimeAudioStatus, build_capabilities
from oi_client.datp import DatpClient
from oi_client.delight import SecretTracker, cycle_pick, format_gateway_about, pick_connecting_quip, pick_surprise_prompt, pick_waiting_quip
from oi_client.state import InvalidTransition, State, StateMachine


class FakeWebSocket:
    def __init__(self, recv_messages: list[str] | None = None):
        self.recv_messages = list(recv_messages or [])
        self.sent_messages: list[dict] = []
        self.closed = False

    async def send(self, raw: str) -> None:
        self.sent_messages.append(json.loads(raw))

    async def recv(self) -> str:
        if not self.recv_messages:
            raise AssertionError("recv called with no queued messages")
        return self.recv_messages.pop(0)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class BrokenCloseWebSocket(FakeWebSocket):
    async def close(self) -> None:
        raise RuntimeError("close failed")


@pytest.mark.asyncio
async def test_connect_returns_false_on_connection_failure(monkeypatch) -> None:
    monkeypatch.setattr("websockets.connect", AsyncMock(side_effect=RuntimeError("no route")))

    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})

    assert await client.connect() is False
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_connect_returns_false_on_timeout(monkeypatch) -> None:
    ws = FakeWebSocket()
    monkeypatch.setattr("websockets.connect", AsyncMock(return_value=ws))

    async def fail_wait_for(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr("asyncio.wait_for", fail_wait_for)

    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})

    assert await client.connect() is False
    assert ws.closed is True
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_disconnect_cancels_listener_and_ignores_close_errors() -> None:
    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})
    client._connected = True
    client._ws = BrokenCloseWebSocket()
    client._listen_task = asyncio.create_task(asyncio.sleep(10))

    await client.disconnect()

    assert client.is_connected is False
    assert client._listen_task is None
    assert client._ws is None


@pytest.mark.asyncio
async def test_listen_loop_marks_disconnected_on_connection_closed(monkeypatch) -> None:
    class FakeClosed(Exception):
        pass

    class ClosingSocket:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise FakeClosed()

    monkeypatch.setitem(sys.modules, "websockets", SimpleNamespace(ConnectionClosed=FakeClosed))

    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})
    client._ws = ClosingSocket()
    client._connected = True

    await client._listen_loop()

    assert client.is_connected is False


@pytest.mark.asyncio
async def test_listen_loop_marks_disconnected_on_unexpected_error(monkeypatch) -> None:
    class FakeClosed(Exception):
        pass

    class BrokenSocket:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise RuntimeError("boom")

    monkeypatch.setitem(sys.modules, "websockets", SimpleNamespace(ConnectionClosed=FakeClosed))

    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})
    client._ws = BrokenSocket()
    client._connected = True

    await client._listen_loop()

    assert client.is_connected is False


@pytest.mark.asyncio
async def test_send_helpers_emit_expected_payloads() -> None:
    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})
    ws = FakeWebSocket()
    client._ws = ws

    await client.send_button("A", action="released")
    await client.send_text_prompt("hello")
    await client.send_state_report(mode="READY", muted_until=None, battery=91)
    await client.send_recording_finished("stream-1", 250)

    assert ws.sent_messages[0]["payload"]["event"] == "button.released"
    assert ws.sent_messages[1]["payload"]["event"] == "text.prompt"
    assert ws.sent_messages[1]["payload"]["text"] == "hello"
    assert ws.sent_messages[1]["payload"]["nonce"]
    assert ws.sent_messages[2]["type"] == "state"
    assert "muted_until" not in ws.sent_messages[2]["payload"]
    assert ws.sent_messages[2]["payload"]["battery"] == 91
    assert ws.sent_messages[3]["payload"] == {
        "event": "audio.recording_finished",
        "stream_id": "stream-1",
        "duration_ms": 250,
    }


@pytest.mark.asyncio
async def test_send_and_ack_are_noops_without_websocket() -> None:
    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})

    await client.send_button("A")
    await client.ack_command("cmd-1", True, op="display.show_card", args={"title": "Done"})

    assert client.state == State.READY


@pytest.mark.asyncio
async def test_ack_command_swallows_invalid_transition_and_still_acks() -> None:
    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})
    ws = FakeWebSocket()
    client._ws = ws
    client.transition(State.ERROR)

    await client.ack_command("cmd-1", True, op="audio.play", args={})

    assert client.state == State.ERROR
    assert ws.sent_messages[-1]["type"] == "ack"
    assert ws.sent_messages[-1]["payload"] == {"command_id": "cmd-1", "ok": True}


@pytest.mark.asyncio
async def test_handle_message_ack_is_noop_and_error_invalid_transition_is_ignored(monkeypatch) -> None:
    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})

    def raise_invalid(self, _state: State) -> None:
        raise InvalidTransition(State.READY, State.ERROR)

    monkeypatch.setattr(StateMachine, "transition", raise_invalid)

    await client._handle_message({"type": "ack", "payload": {}})
    await client._handle_message({"type": "error", "payload": {"code": "bad"}})

    assert client.state == State.READY


def test_transition_swallows_invalid_transition() -> None:
    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})

    client.transition(State.PLAYING)

    assert client.state == State.READY


def test_state_machine_covers_display_status_shutdown_and_no_cache_chunk() -> None:
    machine = StateMachine(State.READY)

    assert machine.receive_command("display.show_status", {"state": "thinking", "label": "Working"}) == State.READY
    assert machine.receive_command("audio.cache.put_chunk") == State.READY
    assert machine.receive_command("storage.format") == State.READY
    assert machine.receive_command("wifi.configure") == State.READY
    assert machine.receive_command("device.shutdown") == State.OFFLINE


def test_state_machine_display_show_card_is_noop_when_transition_invalid() -> None:
    machine = StateMachine(State.ERROR)

    assert machine.receive_command("display.show_card", {"title": "Done"}) == State.ERROR


def test_build_capabilities_without_audio_input() -> None:
    caps = build_capabilities(RuntimeAudioStatus(has_input=False, has_output=True), cols=40, rows=18)

    assert "hold_to_record" not in caps["input"]
    assert caps["supports_voice"] is False
    assert caps["has_audio_output"] is True


def test_delight_helpers_cover_sequences_and_gateway_formatting() -> None:
    tracker = SecretTracker()
    for button in ["up", "up", "nope"]:
        assert tracker.push(button) is False
    assert tracker.progress == 0

    for button in ["up", "up", "down", "down", "left", "right", "left", "right", "b"]:
        assert tracker.push(button) is False
    assert tracker.push("a") is True
    assert tracker.progress == 0

    assert cycle_pick([], 3) == ""
    assert pick_surprise_prompt(6)
    assert pick_connecting_quip(4)
    assert pick_waiting_quip(5)
    assert format_gateway_about(None) == ["No gateway metadata yet."]
    assert format_gateway_about({"payload": {"server_id": "gw-1"}})[0] == "Name: gw-1"
    assert format_gateway_about(
        {
            "payload": {
                "server_name": "Gateway",
                "session_id": "sess-1",
                "accepted_protocol": "datp",
                "default_agent": {"name": "helper"},
                "available_agents": [{"name": "one"}, {"id": "two"}, "three"],
            }
        }
    ) == [
        "Name: Gateway",
        "Session: sess-1",
        "Protocol: datp",
        "Agent: helper",
        "Agents: one, two, three",
    ]
