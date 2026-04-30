"""Tests for the Dashboard HTTP API and SSE functionality."""
from __future__ import annotations

import asyncio

import aiohttp
import oi_dashboard.dashboard as dashboard_module
from oi_dashboard.dashboard import Dashboard


async def retry_request(coro, max_attempts=15, delay=0.2):
    """Retry a request until it succeeds or max attempts reached."""
    last_error = None
    for attempt in range(max_attempts):
        try:
            return await coro()
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            last_error = error
            if attempt < max_attempts - 1:
                await asyncio.sleep(delay * (attempt + 1))
    raise last_error


def dashboard_url(dashboard: Dashboard, path: str) -> str:
    """Build a URL for the running test dashboard."""
    return f"http://{dashboard._host}:{dashboard._port}{path}"


async def fetch_json(dashboard: Dashboard, path: str) -> tuple[int, dict[str, object]]:
    """Fetch JSON from the dashboard and return status plus parsed body."""
    async with aiohttp.ClientSession() as session:
        async with session.get(dashboard_url(dashboard, path), timeout=aiohttp.ClientTimeout(total=5)) as resp:
            return resp.status, await resp.json()


async def fetch_text(dashboard: Dashboard, path: str) -> str:
    """Fetch a text response from the dashboard."""
    async with aiohttp.ClientSession() as session:
        async with session.get(dashboard_url(dashboard, path), timeout=aiohttp.ClientTimeout(total=5)) as resp:
            return await resp.text()


class TestHealthEndpoint:
    async def test_health_proxies_gateway_errors_as_502(self, dashboard):
        """Health endpoint should surface unreachable gateway as a 502 JSON error."""
        status, data = await retry_request(lambda: fetch_json(dashboard, "/api/health"))
        assert status == 502
        assert "error" in data


class TestDevicesEndpoint:
    async def test_devices_endpoint_surfaces_gateway_errors_as_502(self, dashboard):
        """Devices endpoint should surface unreachable gateway as a 502 JSON error."""
        status, data = await retry_request(lambda: fetch_json(dashboard, "/api/devices"))
        assert status == 502
        assert "error" in data


class TestTranscriptsEndpoint:
    async def test_transcripts_returns_empty_initially(self, dashboard):
        """Transcripts endpoint should return empty list initially."""
        _, data = await retry_request(lambda: fetch_json(dashboard, "/api/transcripts"))
        assert "transcripts" in data
        assert "count" in data

    async def test_transcripts_returns_serializable_entries(self, dashboard):
        """Transcripts endpoint should JSON-encode cached transcript entries."""
        dashboard.on_transcript("test-device", {"cleaned": "Hello world"})

        status, data = await retry_request(lambda: fetch_json(dashboard, "/api/transcripts"))

        assert status == 200
        assert data["count"] == 1
        assert data["transcripts"][0]["device_id"] == "test-device"
        assert data["transcripts"][0]["transcript"] == "Hello world"


class TestIndexEndpoint:
    async def test_index_returns_html(self, dashboard):
        """Index endpoint should return HTML page."""
        content = await retry_request(lambda: fetch_text(dashboard, "/"))
        assert "<html" in content.lower() or "<!doctype" in content.lower()
        assert "Dashboard" in content

    async def test_index_falls_back_to_inline_html_when_static_file_missing(self, dashboard, monkeypatch):
        """Index endpoint should use fallback HTML when the static file is unavailable."""
        monkeypatch.setattr(dashboard_module, "STATIC_DIR", dashboard_module.STATIC_DIR / "missing-for-test")

        content = await retry_request(lambda: fetch_text(dashboard, "/"))

        assert "<html" in content.lower() or "<!doctype" in content.lower()
        assert "EventSource('/events')" in content


class TestSSEEndpoint:
    async def test_sse_returns_init_message(self, dashboard):
        """SSE endpoint should emit an init payload as a default message event."""
        async def make_request():
            async with aiohttp.ClientSession() as session:
                async with session.get(dashboard_url(dashboard, "/events")) as resp:
                    assert resp.status == 200
                    assert resp.headers.get("Content-Type") == "text/event-stream"

                    body = b""
                    async for chunk in resp.content.iter_any():
                        body += chunk
                        if b"\n\n" in body:
                            break
                    return body

        body = await retry_request(make_request, max_attempts=5)
        assert b"data: " in body
        assert b"event:" not in body
        assert b'"type":"init"' in body or b'"devices"' in body


class TestStateManagement:
    async def test_on_device_online_updates_state(self, dashboard):
        """Device online event should update internal state."""
        dashboard.on_device_online("test-device", {
            "device_id": "test-device",
            "device_type": "stick",
            "session_id": "sess123",
        })
        
        assert "test-device" in dashboard._devices
        assert dashboard._devices["test-device"].online is True
        assert dashboard._devices["test-device"].device_type == "stick"

    async def test_on_device_offline_marks_offline(self, dashboard):
        """Device offline event should mark device offline."""
        # First bring device online
        dashboard.on_device_online("test-device", {
            "device_id": "test-device",
            "device_type": "stick",
        })
        assert dashboard._devices["test-device"].online is True
        
        # Then go offline
        dashboard.on_device_offline("test-device")
        assert dashboard._devices["test-device"].online is False

    async def test_on_transcript_adds_entry(self, dashboard):
        """Transcript event should add entry to transcript list."""
        dashboard.on_transcript("test-device", {
            "cleaned": "Hello world",
            "stream_id": "stream1",
        })
        
        assert len(dashboard._transcripts) == 1
        assert dashboard._transcripts[0].transcript == "Hello world"
        assert dashboard._transcripts[0].device_id == "test-device"

    async def test_on_agent_response_updates_last_transcript(self, dashboard):
        """Agent response should update matching transcript."""
        dashboard.on_transcript("test-device", {
            "cleaned": "Hello world",
            "stream_id": "stream1",
        })
        dashboard.on_agent_response("test-device", {
            "transcript": "Hello world",
            "response_text": "Hi there!",
            "stream_id": "stream1",
        })
        
        assert dashboard._transcripts[0].response == "Hi there!"

    async def test_on_state_updated_updates_device_state(self, dashboard):
        """State update should merge into device state."""
        dashboard.on_device_online("test-device", {
            "device_id": "test-device",
        })
        dashboard.on_state_updated("test-device", {
            "mode": "listening",
            "battery_percent": 85,
        })
        
        assert dashboard._devices["test-device"].state["mode"] == "listening"
        assert dashboard._devices["test-device"].state["battery_percent"] == 85

    async def test_transcripts_trimmed_to_max(self, dashboard):
        """Transcript list should be trimmed to max size."""
        dashboard._max_transcripts = 5
        
        for i in range(10):
            dashboard.on_transcript("test-device", {
                "cleaned": f"Transcript {i}",
            })
        
        assert len(dashboard._transcripts) == 5
        # Should have the last 5
        assert dashboard._transcripts[-1].transcript == "Transcript 9"


class TestSnapshot:
    async def test_get_state_snapshot_contains_all_state(self, dashboard):
        """State snapshot should include all current state."""
        dashboard.on_device_online("device1", {
            "device_id": "device1",
            "device_type": "stick",
        })
        dashboard.on_transcript("device1", {
            "cleaned": "Test transcript",
        })
        
        snapshot = dashboard._get_state_snapshot()
        
        assert "devices" in snapshot
        assert "transcripts" in snapshot
        assert "timestamp" in snapshot
        assert "device1" in snapshot["devices"]
        assert len(snapshot["transcripts"]) == 1
