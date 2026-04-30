from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oi_client.datp import DatpClient  # noqa: E402
from oi_client.telemetry import TelemetryCollector  # noqa: E402


def test_telemetry_collects_core_fields() -> None:
    collector = TelemetryCollector(start_time=100.0)
    payload = collector.collect(mode="READY", muted_until=None, audio_cache_used_bytes=123)
    assert payload["mode"] == "READY"
    assert payload["audio_cache_used_bytes"] == 123
    assert payload["uptime_s"] >= 0
    assert "muted_until" in payload


def test_connect_stores_server_info() -> None:
    client = DatpClient("ws://example", "dev-1", "handheld", {})

    class FakeConnectionClosed(Exception):
        pass

    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.closed = False
            self._iterated = False

        async def send(self, data: str) -> None:
            self.sent.append(data)

        async def recv(self) -> str:
            return '{"type":"hello_ack","payload":{"session_id":"sess-1","server_name":"Oi Gateway"}}'

        async def close(self) -> None:
            self.closed = True

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.closed or self._iterated:
                raise StopAsyncIteration
            self._iterated = True
            raise FakeConnectionClosed()

    async def fake_connect(*args, **kwargs):
        return FakeWebSocket()

    import types
    import sys as _sys
    old = _sys.modules.get("websockets")
    _sys.modules["websockets"] = types.SimpleNamespace(connect=fake_connect, ConnectionClosed=FakeConnectionClosed)
    try:
        assert asyncio.run(client.connect()) is True
        assert client.server_info is not None
        assert client.server_info["payload"]["server_name"] == "Oi Gateway"
        asyncio.run(client.disconnect())
    finally:
        if old is None:
            del _sys.modules["websockets"]
        else:
            _sys.modules["websockets"] = old


def test_send_state_report_merges_optional_fields() -> None:
    client = DatpClient("ws://example", "dev-1", "handheld", {})
    captured: list[tuple[str, dict]] = []

    async def fake_send(msg_type: str, payload: dict) -> None:
        captured.append((msg_type, payload))

    client._send = fake_send  # type: ignore[method-assign]

    asyncio.run(client.send_state_report(muted_until="2026-04-30T00:00:00.000Z", wifi_rssi=-55))

    assert captured == [(
        "state",
        {"mode": "READY", "muted_until": "2026-04-30T00:00:00.000Z", "wifi_rssi": -55},
    )]
