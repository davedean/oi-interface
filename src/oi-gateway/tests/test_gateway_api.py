"""Tests for the GatewayAPI HTTP endpoints."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Ensure src is on the path
gateway_src = Path(__file__).parent.parent / "src"
if str(gateway_src) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(gateway_src))

from audio.tts import StubTtsBackend
from datp import CommandDispatcher, EventBus
from datp.server import DATPServer
from api import GatewayAPI
from registry import DeviceStore, RegistryService


@pytest.fixture
async def datp_server():
    """Start an ephemeral DATP server."""
    srv = DATPServer(host="localhost", port=0)
    await srv.start()
    yield srv
    await srv.stop()


@pytest.fixture
async def gateway_api(tmp_path):
    """Start GatewayAPI with a DATP server and RegistryService."""
    db_path = str(tmp_path / "test-gateway.db")
    store = DeviceStore(db_path)
    event_bus = EventBus()
    registry = RegistryService(store, event_bus)
    await registry.start()

    datp_server = DATPServer(
        host="localhost",
        port=0,
        event_bus=event_bus,
        registry=registry,
    )
    await datp_server.start()

    dispatcher = CommandDispatcher(datp_server)
    api = GatewayAPI(
        datp_server=datp_server,
        command_dispatcher=dispatcher,
        event_bus=event_bus,
        host="localhost",
        port=0,
        tts=StubTtsBackend(),
    )
    await api.start()

    yield api

    await api.stop()
    await registry.stop()
    await datp_server.stop()
    store.close()


class TestHealthEndpoint:
    async def test_health_returns_ok(self, gateway_api):
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/health"
        # Retry a few times in case the server just started
        async with aiohttp.ClientSession() as session:
            for attempt in range(5):
                try:
                    async with session.get(url) as resp:
                        data = await resp.json()
                        break
                except aiohttp.ClientConnectorError:
                    if attempt < 4:
                        await asyncio.sleep(0.2 * (attempt + 1))
                        continue
                    raise
        assert data["status"] == "ok"
        assert "datp_running" in data
        assert "devices_online" in data
        assert "timestamp" in data

    async def test_health_has_correct_fields(self, gateway_api):
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/health"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                assert resp.status == 200
                data = await resp.json()
        assert "timestamp" in data


class TestDevicesEndpoint:
    async def test_devices_empty(self, gateway_api):
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/devices"
        async with aiohttp.ClientSession() as session:
            for attempt in range(5):
                try:
                    async with session.get(url) as resp:
                        data = await resp.json()
                        break
                except aiohttp.ClientConnectorError:
                    if attempt < 4:
                        await asyncio.sleep(0.2 * (attempt + 1))
                        continue
                    raise
        assert data["devices"] == []
        assert data["count"] == 0


class TestTranscriptEndpoint:
    async def test_transcripts_reflect_event_bus_activity(self, gateway_api):
        import aiohttp

        gateway_api._event_bus.emit("transcript", "dev-1", {
            "cleaned": "Hello there",
            "stream_id": "stream-1",
        })
        gateway_api._event_bus.emit("agent_response", "dev-1", {
            "transcript": "Hello there",
            "response_text": "Hi!",
            "stream_id": "stream-1",
        })

        url = f"http://{gateway_api._host}:{gateway_api._port}/api/transcripts"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                assert resp.status == 200
                data = await resp.json()

        assert data["count"] == 1
        assert data["transcripts"][0]["device_id"] == "dev-1"
        assert data["transcripts"][0]["transcript"] == "Hello there"
        assert data["transcripts"][0]["response"] == "Hi!"


class TestConversationEndpoints:
    async def _add_device(self, gateway_api, device_id):
        gateway_api._datp.device_registry[device_id] = {
            "device_id": device_id,
            "session_id": f"session-{device_id}",
            "capabilities": {},
            "conversation": {
                "backend_id": "pi",
                "agent_id": "main",
                "session_key": f"oi:device:{device_id}",
            },
        }
        gateway_api._datp.available_backends = [{"id": "pi", "name": "Pi"}, {"id": "codex", "name": "Codex"}]
        gateway_api._datp.default_backend_id = "pi"
        gateway_api._datp.default_agent = {"id": "main", "name": "Main"}
        gateway_api._datp.available_agents = [gateway_api._datp.default_agent, {"id": "build", "name": "Build"}]

    async def test_get_device_conversation(self, gateway_api):
        import aiohttp
        await self._add_device(gateway_api, "dev-conversation")

        url = f"http://{gateway_api._host}:{gateway_api._port}/api/devices/dev-conversation/conversation"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                assert resp.status == 200
                data = await resp.json()

        assert data["conversation"] == {
            "backend_id": "pi",
            "agent_id": "main",
            "session_key": "oi:device:dev-conversation",
        }
        assert data["available_backends"][1]["id"] == "codex"

    async def test_post_device_conversation_validates_and_updates(self, gateway_api):
        import aiohttp
        await self._add_device(gateway_api, "dev-conversation")

        url = f"http://{gateway_api._host}:{gateway_api._port}/api/devices/dev-conversation/conversation"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"backend_id": "codex", "agent_id": "build", "session_key": "oi:session:new"}) as resp:
                assert resp.status == 200
                data = await resp.json()
            async with session.post(url, json=[]) as resp:
                assert resp.status == 400
            async with session.post(url, json={"conversation": []}) as resp:
                assert resp.status == 400
                nested_err = await resp.json()
            async with session.post(url, json={"backend_id": "missing"}) as resp:
                assert resp.status == 400
                err = await resp.json()

        assert data["conversation"] == {
            "backend_id": "codex",
            "agent_id": "build",
            "session_key": "oi:session:new",
        }
        assert gateway_api._datp.get_device_conversation("dev-conversation") == data["conversation"]
        assert "conversation must be a JSON object" in nested_err["error"]
        assert "backend_id" in err["error"]


class TestCommandEndpoints:
    async def _add_device(self, gateway_api, device_id):
        gateway_api._datp.device_registry[device_id] = {
            "device_id": device_id,
            "session_id": f"session-{device_id}",
            "capabilities": {},
        }

    async def test_show_status_device_not_found(self, gateway_api):
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/devices/nonexistent/commands/show_status"
        body = json.dumps({"state": "thinking", "label": "Working"})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 404
                data = await resp.json()
        assert "error" in data

    async def test_mute_device_not_found(self, gateway_api):
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/devices/nonexistent/commands/mute_until"
        body = json.dumps({"minutes": 30})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 404

    async def test_audio_play_device_not_found(self, gateway_api):
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/devices/nonexistent/commands/audio_play"
        body = json.dumps({})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 404

    async def test_show_status_mute_and_audio_play_success(self, gateway_api):
        import aiohttp
        await self._add_device(gateway_api, "dev-success")
        gateway_api._dispatcher.show_status = AsyncMock(return_value=True)
        gateway_api._dispatcher.mute_until = AsyncMock(return_value=True)
        gateway_api._dispatcher.audio_play = AsyncMock(return_value=True)

        async with aiohttp.ClientSession() as session:
            base = f"http://{gateway_api._host}:{gateway_api._port}/api/devices/dev-success/commands"
            async with session.post(f"{base}/show_status", json={"state": "thinking", "label": "Working"}) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["ok"] is True
                assert data["command"] == "display.show_status"

            async with session.post(f"{base}/mute_until", json={"minutes": 1}) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["minutes"] == 1
                assert data["command"] == "device.mute_until"

            async with session.post(f"{base}/audio_play", json={}) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["response_id"] == "latest"


class TestRouteEndpoint:
    async def test_route_device_not_found(self, gateway_api):
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/route"
        body = json.dumps({"device_id": "nonexistent", "text": "Hello"})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 404

    async def test_route_missing_device_id(self, gateway_api):
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/route"
        body = json.dumps({"text": "Hello"})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                # Should return error: no device_id provided - uses routing policy
                assert resp.status == 500  # No devices available
                data = await resp.json()
                assert "No devices available" in data["error"]

    async def test_route_missing_text(self, gateway_api):
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/route"
        body = json.dumps({"device_id": "some-device"})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 400

    async def test_route_empty_text(self, gateway_api):
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/route"
        body = json.dumps({"device_id": "some-device", "text": "   "})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 400


class TestMultiDeviceRouteEndpoint:
    """Tests for multi-device routing via /api/route endpoint."""

    async def _add_device(self, gateway_api, device_id, capabilities=None):
        """Helper to add a mock device to the registry."""
        caps = capabilities or {}
        gateway_api._datp.device_registry[device_id] = {
            "device_id": device_id,
            "session_id": f"session-{device_id}",
            "capabilities": caps,
        }

    async def test_route_multi_device_ids_must_be_array(self, gateway_api):
        """Test that device_ids must be an array."""
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/route"
        body = json.dumps({"device_ids": "not-an-array", "text": "Hello"})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 400
                data = await resp.json()
                assert "array" in data["error"].lower()

    async def test_route_multi_empty_device_ids(self, gateway_api):
        """Test that device_ids cannot be empty array."""
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/route"
        body = json.dumps({"device_ids": [], "text": "Hello"})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 400
                data = await resp.json()
                assert "empty" in data["error"].lower()

    async def test_route_multi_missing_devices(self, gateway_api):
        """Test that missing devices return 404."""
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/route"
        body = json.dumps({"device_ids": ["nonexistent1", "nonexistent2"], "text": "Hello"})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 404
                data = await resp.json()
                assert "not found" in data["error"].lower()

    async def test_route_multi_with_valid_devices(self, gateway_api):
        """Test multi-device routing with valid devices returns routing metadata."""
        import aiohttp
        await self._add_device(gateway_api, "speaker1", {"is_foreground_device": True})
        await self._add_device(gateway_api, "speaker2", {"is_foreground_device": True})
        gateway_api._send_audio_to_device = AsyncMock(side_effect=lambda device_id, response_id, pcm_chunks: {
            "device_id": device_id,
            "response_id": response_id,
            "chunks_sent": len(pcm_chunks),
        })

        url = f"http://{gateway_api._host}:{gateway_api._port}/api/route"
        body = json.dumps({"device_ids": ["speaker1", "speaker2"], "text": "Hello world"})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 200
                data = await resp.json()
        assert data["ok"] is True
        assert data["device_ids"] == ["speaker1", "speaker2"]
        assert len(data["devices"]) == 2
        assert data["routing"]["policy_reason"]

    async def test_route_multi_mixed_valid_invalid_devices(self, gateway_api):
        """Test mixed valid/invalid device IDs."""
        import aiohttp
        await self._add_device(gateway_api, "speaker1", {"is_foreground_device": True})

        url = f"http://{gateway_api._host}:{gateway_api._port}/api/route"
        body = json.dumps({"device_ids": ["speaker1", "nonexistent"], "text": "Hello"})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 404
                data = await resp.json()
                assert "nonexistent" in data["error"]

    async def test_route_auto_routing_no_devices(self, gateway_api):
        """Test auto-routing when no devices available."""
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/route"
        body = json.dumps({"text": "Hello"})  # No device specified
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 500
                data = await resp.json()
                assert "No devices available" in data["error"]

    async def test_route_auto_routing_short_text(self, gateway_api):
        """Test auto-routing selects a single device for short text."""
        import aiohttp
        await self._add_device(gateway_api, "speaker1", {"is_foreground_device": True})
        await self._add_device(gateway_api, "speaker2", {"is_foreground_device": True})
        gateway_api._send_audio_to_device = AsyncMock(side_effect=lambda device_id, response_id, pcm_chunks: {
            "device_id": device_id,
            "response_id": response_id,
            "chunks_sent": len(pcm_chunks),
        })

        url = f"http://{gateway_api._host}:{gateway_api._port}/api/route"
        body = json.dumps({"text": "Hi there"})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 200
                data = await resp.json()
        assert data["ok"] is True
        assert len(data["device_ids"]) == 1
        assert len(data["devices"]) == 1


class TestRouteMultiEndpoint:
    """Tests for the dedicated /api/route/multi endpoint."""

    async def _add_device(self, gateway_api, device_id, capabilities=None):
        """Helper to add a mock device to the registry."""
        caps = capabilities or {}
        gateway_api._datp.device_registry[device_id] = {
            "device_id": device_id,
            "session_id": f"session-{device_id}",
            "capabilities": caps,
        }

    async def test_route_multi_endpoint_exists(self, gateway_api):
        """Test that /api/route/multi endpoint exists."""
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/route/multi"
        body = json.dumps({"text": "Hello"})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                # Should return 500 (no devices) not 404 (endpoint not found)
                assert resp.status == 500

    async def test_route_multi_missing_text(self, gateway_api):
        """Test /api/route/multi requires text."""
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/route/multi"
        body = json.dumps({})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 400

    async def test_route_multi_long_text_force_multiple(self, gateway_api):
        """Test /api/route/multi returns detailed routing info for long text."""
        import aiohttp
        await self._add_device(gateway_api, "speaker1", {"is_foreground_device": True})
        await self._add_device(gateway_api, "dashboard1", {"is_background_device": True})
        gateway_api._send_audio_to_device = AsyncMock(side_effect=lambda device_id, response_id, pcm_chunks: {
            "device_id": device_id,
            "response_id": response_id,
            "chunks_sent": len(pcm_chunks),
        })

        long_text = " ".join(["word"] * 150)

        url = f"http://{gateway_api._host}:{gateway_api._port}/api/route/multi"
        body = json.dumps({"text": long_text, "force_multiple": True})
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=body, headers={"Content-Type": "application/json"}) as resp:
                assert resp.status == 200
                data = await resp.json()
        assert data["ok"] is True
        assert len(data["device_ids"]) >= 1
        assert data["routing"]["estimated_duration_seconds"] > 0


class TestStabilityEndpoints:
    """Tests for stability API endpoints."""

    async def _add_device(self, gateway_api, device_id, capabilities=None):
        """Helper to add a mock device to the registry.

        Adds the device to both the DATPServer's device_registry and
        the RegistryService's store (SQLite).
        """
        caps = capabilities or {}
        # Add to DATPServer's device_registry
        gateway_api._datp.device_registry[device_id] = {
            "device_id": device_id,
            "session_id": f"session-{device_id}",
            "capabilities": caps,
        }
        # Add to RegistryService's store (SQLite) so stability endpoints work
        if gateway_api._datp.registry:
            await gateway_api._datp.registry.device_registered(
                device_id=device_id,
                device_type="test-device",
                session_id=f"session-{device_id}",
                capabilities=caps,
                resume_token=None,
                nonce=None,
                state={},
            )

    async def test_set_foreground_device(self, gateway_api):
        """Test POST /api/devices/{device_id}/foreground sets foreground."""
        import aiohttp
        # Register a device first
        await self._add_device(gateway_api, "foreground-test")

        url = f"http://{gateway_api._host}:{gateway_api._port}/api/devices/foreground-test/foreground"
        async with aiohttp.ClientSession() as session:
            async with session.post(url) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["ok"] is True
                assert data["device_id"] == "foreground-test"
                assert "message" in data

    async def test_set_foreground_device_not_found(self, gateway_api):
        """Test POST /api/devices/{device_id}/foreground returns 404 for unknown device."""
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/devices/nonexistent/foreground"
        async with aiohttp.ClientSession() as session:
            async with session.post(url) as resp:
                assert resp.status == 404

    async def test_device_health(self, gateway_api):
        """Test GET /api/devices/{device_id}/health returns health status."""
        import aiohttp
        # Register a device first
        await self._add_device(gateway_api, "health-test")

        url = f"http://{gateway_api._host}:{gateway_api._port}/api/devices/health-test/health"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["device_id"] == "health-test"
                assert "is_healthy" in data
                assert "is_online" in data
                assert "last_heartbeat" in data
                assert "heartbeat_timeout" in data

    async def test_device_health_not_found(self, gateway_api):
        """Test GET /api/devices/{device_id}/health returns 404 for unknown device."""
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/devices/nonexistent/health"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                assert resp.status == 404

    async def test_record_interaction(self, gateway_api):
        """Test POST /api/devices/{device_id}/interactions records interaction."""
        import aiohttp
        # Register a device first
        await self._add_device(gateway_api, "interaction-test")

        url = f"http://{gateway_api._host}:{gateway_api._port}/api/devices/interaction-test/interactions"
        async with aiohttp.ClientSession() as session:
            async with session.post(url) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["ok"] is True
                assert data["device_id"] == "interaction-test"
                assert "last_interaction" in data

    async def test_record_interaction_not_found(self, gateway_api):
        """Test POST /api/devices/{device_id}/interactions returns 404 for unknown device."""
        import aiohttp
        url = f"http://{gateway_api._host}:{gateway_api._port}/api/devices/nonexistent/interactions"
        async with aiohttp.ClientSession() as session:
            async with session.post(url) as resp:
                assert resp.status == 404