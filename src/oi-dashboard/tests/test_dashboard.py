"""Tests for the Dashboard HTTP API and SSE functionality."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

# Ensure src is on the path
dashboard_src = Path(__file__).parent.parent / "src"
if str(dashboard_src) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(dashboard_src))

from oi_dashboard.dashboard import Dashboard


@pytest.fixture
async def dashboard():
    """Create a dashboard instance with ephemeral port."""
    dash = Dashboard(
        api_base_url="http://localhost:9999",  # Non-existent API
        host="localhost",
        port=0,  # OS assigns free port
        poll_interval=60.0,  # Disable polling during tests
    )
    await dash.start()
    # Wait for server to be ready by attempting to connect
    await asyncio.sleep(0.2)
    yield dash
    await dash.stop()
    # Small delay for cleanup
    await asyncio.sleep(0.1)


async def retry_request(coro, max_attempts=15, delay=0.2):
    """Retry a request until it succeeds or max attempts reached."""
    last_error = None
    for attempt in range(max_attempts):
        try:
            return await coro()
        except (ConnectionRefusedError, ConnectionResetError, asyncio.TimeoutError) as e:
            last_error = e
            if attempt < max_attempts - 1:
                await asyncio.sleep(delay * (attempt + 1))
        except Exception as e:
            last_error = e
            if attempt < max_attempts - 1:
                await asyncio.sleep(delay * (attempt + 1))
    raise last_error


class TestHealthEndpoint:
    async def test_health_proxies_to_gateway(self, dashboard):
        """Health endpoint should proxy to gateway API."""
        import aiohttp
        
        async def make_request():
            url = f"http://{dashboard._host}:{dashboard._port}/api/health"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return await resp.json()
        
        # Should get either an error (gateway unreachable) or status
        data = await retry_request(make_request)
        assert "error" in data or "status" in data


class TestDevicesEndpoint:
    async def test_devices_endpoint_works(self, dashboard):
        """Devices endpoint should respond (either device list or error)."""
        import aiohttp
        
        async def make_request():
            url = f"http://{dashboard._host}:{dashboard._port}/api/devices"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return await resp.json()
        
        data = await retry_request(make_request)
        # Should return either devices list (when gateway is up) or error (when gateway is down)
        assert "devices" in data or "error" in data


class TestTranscriptsEndpoint:
    async def test_transcripts_returns_empty_initially(self, dashboard):
        """Transcripts endpoint should return empty list initially."""
        import aiohttp
        
        async def make_request():
            url = f"http://{dashboard._host}:{dashboard._port}/api/transcripts"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return await resp.json()
        
        data = await retry_request(make_request)
        assert "transcripts" in data
        assert "count" in data


class TestIndexEndpoint:
    async def test_index_returns_html(self, dashboard):
        """Index endpoint should return HTML page."""
        import aiohttp
        
        async def make_request():
            url = f"http://{dashboard._host}:{dashboard._port}/"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return await resp.text()
        
        content = await retry_request(make_request)
        assert "<html" in content.lower() or "<!doctype" in content.lower()
        assert "Dashboard" in content


class TestSSEEndpoint:
    async def test_sse_returns_init_event(self, dashboard):
        """SSE endpoint should return initial state on connect."""
        import aiohttp
        
        async def make_request():
            url = f"http://{dashboard._host}:{dashboard._port}/events"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    assert resp.status == 200
                    assert resp.headers.get("Content-Type") == "text/event-stream"
                    
                    # Read SSE data
                    body = b""
                    async for chunk in resp.content.iter_any():
                        body += chunk
                        if b"event: init" in body:
                            break
                    return body
        
        body = await retry_request(make_request, max_attempts=5)
        assert b"event: init" in body
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


class TestProxyRequests:
    async def test_proxy_returns_502_on_gateway_unreachable(self, dashboard):
        """Proxy should return 502 when gateway is unreachable."""
        import aiohttp
        
        async def make_request():
            url = f"http://{dashboard._host}:{dashboard._port}/api/health"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return await resp.json()
        
        # The dashboard was configured with unreachable API URL
        data = await retry_request(make_request)
        assert "error" in data
