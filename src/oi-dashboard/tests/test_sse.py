"""Unit tests for the dashboard SSE transport adapter."""
from __future__ import annotations

import asyncio
import json

from oi_dashboard.sse import SseHub


class FakeClient:
    def __init__(self, prepared: bool = True) -> None:
        self.prepared = prepared
        self.writes: list[bytes] = []
        self.closed = False

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def write_eof(self) -> None:
        self.closed = True


async def test_send_event_writes_default_message_frame() -> None:
    hub = SseHub()
    client = FakeClient()

    await hub.send_event(client, "init", {"ready": True})

    assert client.writes == [b'data: {"type": "init", "data": {"ready": true}}\n\n']


async def test_send_event_skips_unprepared_clients() -> None:
    hub = SseHub()
    client = FakeClient(prepared=False)

    await hub.send_event(client, "init", {"ready": True})

    assert client.writes == []


async def test_close_finishes_all_connected_clients() -> None:
    hub = SseHub()
    client_a = FakeClient()
    client_b = FakeClient(prepared=False)
    hub.clients.update({client_a, client_b})

    await hub.close()

    assert client_a.closed is True
    assert client_b.closed is False


async def test_broadcast_schedules_send_for_each_client(monkeypatch) -> None:
    hub = SseHub()
    client_a = FakeClient()
    client_b = FakeClient()
    hub.clients.update({client_a, client_b})
    scheduled: list[asyncio.Task] = []

    def capture(task):
        scheduled.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", capture)

    hub.broadcast("device_online", {"device_id": "dev-1"})

    assert len(scheduled) == 2
    await asyncio.gather(*scheduled)
    payload = json.dumps({"type": "device_online", "data": {"device_id": "dev-1"}}).encode()
    assert client_a.writes == [b"data: " + payload + b"\n\n"]
    assert client_b.writes == [b"data: " + payload + b"\n\n"]
