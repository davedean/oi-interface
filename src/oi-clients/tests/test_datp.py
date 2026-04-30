"""Tests for the handheld DATP client."""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


client_src = Path(__file__).parent.parent / "generic_sbc_handheld"
if str(client_src) not in sys.path:
    sys.path.insert(0, str(client_src))

from oi_client.datp import DatpClient
from oi_client.state import State


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


@pytest.mark.asyncio
async def test_connect_sends_hello_and_starts_listener(monkeypatch) -> None:
    ws = FakeWebSocket([
        json.dumps({"type": "hello_ack", "payload": {"session_id": "sess-1"}})
    ])

    monkeypatch.setattr("websockets.connect", AsyncMock(return_value=ws))

    client = DatpClient(
        gateway="ws://gateway/datp",
        device_id="dev1",
        device_type="handheld",
        capabilities={"audio_out": True},
        backend_id="pi",
        agent_id="main",
        session_key="oi:session:test",
    )

    connected = await client.connect()

    assert connected is True
    assert client.is_connected is True
    assert client._session_id == "sess-1"
    assert ws.sent_messages[0]["type"] == "hello"
    assert ws.sent_messages[0]["payload"]["capabilities"] == {"audio_out": True}
    assert ws.sent_messages[0]["payload"]["conversation"] == {
        "backend_id": "pi",
        "agent_id": "main",
        "session_key": "oi:session:test",
    }

    await client.disconnect()


@pytest.mark.asyncio
async def test_connect_returns_false_on_unexpected_hello_ack(monkeypatch) -> None:
    ws = FakeWebSocket([json.dumps({"type": "ack", "payload": {}})])
    monkeypatch.setattr("websockets.connect", AsyncMock(return_value=ws))

    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})

    assert await client.connect() is False
    assert ws.closed is True
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_handle_command_updates_state_sends_ack_and_queues_payload() -> None:
    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})
    ws = FakeWebSocket()
    client._ws = ws

    await client._handle_message(
        {
            "id": "cmd1",
            "type": "command",
            "payload": {"op": "display.show_card", "args": {"title": "Done"}},
        }
    )

    assert client.state == State.READY
    assert client.get_commands() == [{"op": "display.show_card", "args": {"title": "Done"}}]
    assert ws.sent_messages[-1]["type"] == "ack"
    assert ws.sent_messages[-1]["payload"]["command_id"] == "cmd1"


@pytest.mark.asyncio
async def test_handle_error_transitions_to_error_state() -> None:
    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})

    await client._handle_message({"type": "error", "payload": {"code": "bad"}})

    assert client.state == State.ERROR


@pytest.mark.asyncio
async def test_send_audio_chunk_encodes_pcm_as_base64() -> None:
    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})
    ws = FakeWebSocket()
    client._ws = ws

    await client.send_audio_chunk("stream1", 7, b"\x01\x02\x03\x04", sample_rate=24000)

    msg = ws.sent_messages[-1]
    assert msg["type"] == "audio_chunk"
    assert msg["payload"]["stream_id"] == "stream1"
    assert msg["payload"]["seq"] == 7
    assert msg["payload"]["sample_rate"] == 24000
    assert base64.b64decode(msg["payload"]["data_b64"]) == b"\x01\x02\x03\x04"


@pytest.mark.asyncio
async def test_send_failure_marks_client_disconnected() -> None:
    class BrokenWebSocket(FakeWebSocket):
        async def send(self, raw: str) -> None:
            raise RuntimeError("broken")

    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})
    client._ws = BrokenWebSocket()
    client._connected = True

    with pytest.raises(RuntimeError, match="broken"):
        await client.send_button("A")

    assert client.is_connected is False


@pytest.mark.asyncio
async def test_reconnect_resets_session_commands_and_state(monkeypatch) -> None:
    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {}, reconnect_backoff=0)
    client._session_id = "old-session"
    client._received_commands = [{"op": "x"}]
    client.transition(State.RECORDING)

    disconnect = AsyncMock()
    connect = AsyncMock(return_value=True)
    monkeypatch.setattr(client, "disconnect", disconnect)
    monkeypatch.setattr(client, "connect", connect)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    result = await client.reconnect()

    assert result is True
    disconnect.assert_awaited_once()
    connect.assert_awaited_once()
    assert client._session_id is None
    assert client._received_commands == []
    assert client.state == State.READY


def test_get_commands_drains_queue() -> None:
    client = DatpClient("ws://gateway/datp", "dev1", "handheld", {})
    client._cmd_queue.put_nowait({"op": "one"})
    client._cmd_queue.put_nowait({"op": "two"})

    assert client.get_commands() == [{"op": "one"}, {"op": "two"}]
    assert client.get_commands() == []
