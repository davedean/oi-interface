"""Unit tests for the dashboard gateway HTTP adapter."""
from __future__ import annotations

import aiohttp
import pytest

from oi_dashboard.gateway_api import GatewayApi


class FakeResponse:
    def __init__(self, status: int, body: dict[str, object]) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def json(self) -> dict[str, object]:
        return self._body


class FakeSession:
    def __init__(self, response: FakeResponse, calls: list[tuple[str, float | None]]) -> None:
        self._response = response
        self._calls = calls

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def get(self, url: str, timeout: aiohttp.ClientTimeout):
        self._calls.append((url, timeout.total))
        return self._response


@pytest.mark.asyncio
async def test_get_devices_uses_devices_route(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, float | None]] = []

    monkeypatch.setattr(
        "oi_dashboard.gateway_api.aiohttp.ClientSession",
        lambda: FakeSession(FakeResponse(200, {"devices": []}), calls),
    )

    api = GatewayApi("http://gateway:8788")
    status, body = await api.get_devices()

    assert status == 200
    assert body == {"devices": []}
    assert calls == [("http://gateway:8788/api/devices", 5)]


@pytest.mark.asyncio
async def test_get_device_info_uses_device_route(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, float | None]] = []

    monkeypatch.setattr(
        "oi_dashboard.gateway_api.aiohttp.ClientSession",
        lambda: FakeSession(FakeResponse(200, {"device_id": "dev-1"}), calls),
    )

    api = GatewayApi("http://gateway:8788/")
    status, body = await api.get_device_info("dev-1")

    assert status == 200
    assert body == {"device_id": "dev-1"}
    assert calls == [("http://gateway:8788/api/devices/dev-1", 5)]


@pytest.mark.asyncio
async def test_get_health_uses_health_route(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, float | None]] = []

    monkeypatch.setattr(
        "oi_dashboard.gateway_api.aiohttp.ClientSession",
        lambda: FakeSession(FakeResponse(200, {"devices_online": 2}), calls),
    )

    api = GatewayApi("http://gateway:8788")
    status, body = await api.get_health()

    assert status == 200
    assert body == {"devices_online": 2}
    assert calls == [("http://gateway:8788/api/health", 5)]
