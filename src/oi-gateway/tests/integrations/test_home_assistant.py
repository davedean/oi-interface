"""Tests for Home Assistant adapter."""
from __future__ import annotations
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientError

# Skip unless explicitly enabled (requires running Home Assistant server)
pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_HA_TESTS"),
    reason="Requires running Home Assistant server. Set RUN_HA_TESTS=1 to enable."
)

from integrations.home_assistant import (
    HAEntity,
    HAEvent,
    HAService,
    HomeAssistantAdapter,
    HomeAssistantAdapterError,
    HomeAssistantAPIError,
    HomeAssistantConnectionError,
)


class TestHAEntity:
    """Tests for HAEntity dataclass."""

    def test_entity_creation(self):
        """Test entity creation."""
        entity = HAEntity(
            entity_id="light.living_room",
            state="on",
            attributes={"brightness": 255},
            last_changed="2024-01-01T00:00:00",
            last_updated="2024-01-01T00:00:00",
        )
        assert entity.entity_id == "light.living_room"
        assert entity.state == "on"
        assert entity.attributes["brightness"] == 255


class TestHAEvent:
    """Tests for HAEvent dataclass."""

    def test_event_creation(self):
        """Test event creation."""
        event = HAEvent(
            event_type="state_changed",
            data={"entity_id": "light.test", "new_state": "on"},
            origin="LOCAL",
            time_fired="2024-01-01T00:00:00",
        )
        assert event.event_type == "state_changed"
        assert event.data["entity_id"] == "light.test"


class TestHAService:
    """Tests for HAService dataclass."""

    def test_service_creation(self):
        """Test service creation."""
        service = HAService(
            domain="light",
            service="turn_on",
            services={"turn_on": {"description": "Turn on light"}},
        )
        assert service.domain == "light"
        assert service.service == "turn_on"


class TestHomeAssistantAdapter:
    """Tests for HomeAssistantAdapter."""

    @pytest.fixture
    def adapter(self):
        """Create an adapter instance."""
        return HomeAssistantAdapter(
            base_url="http://homeassistant:8123",
            token="test-token",
            timeout=30.0,
        )

    def test_init(self, adapter):
        """Test adapter initialization."""
        assert adapter._base_url == "http://homeassistant:8123"
        assert adapter._token == "test-token"
        assert adapter._connected is False

    def test_get_headers(self, adapter):
        """Test headers include auth token."""
        headers = adapter._get_headers()
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_connect_success(self, adapter):
        """Test successful connection."""
        mock_response = AsyncMock()
        mock_response.status = 200

        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response

            result = await adapter.connect()
            assert result is True
            assert adapter._connected is True

    @pytest.mark.asyncio
    async def test_connect_failure(self, adapter):
        """Test failed connection."""
        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value.get.side_effect = ClientError("Connection refused")

            result = await adapter.connect()
            assert result is False
            assert adapter._connected is False

    @pytest.mark.asyncio
    async def test_disconnect(self, adapter):
        """Test disconnection."""
        adapter._session = MagicMock()
        adapter._connected = True
        adapter._event_stream_task = asyncio.create_task(asyncio.sleep(10))

        await adapter.disconnect()

        assert adapter._session is None
        assert adapter._connected is False
        assert adapter._event_stream_task is None

    @pytest.mark.asyncio
    async def test_get_states_not_connected(self, adapter):
        """Test get_states when not connected."""
        with pytest.raises(HomeAssistantConnectionError, match="Not connected"):
            await adapter.get_states()

    @pytest.mark.asyncio
    async def test_get_states_success(self, adapter):
        """Test successful get_states."""
        adapter._connected = True
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=[
            {"entity_id": "light.living_room", "state": "on", "attributes": {}, "last_changed": "", "last_updated": ""},
            {"entity_id": "switch.garage", "state": "off", "attributes": {}, "last_changed": "", "last_updated": ""},
        ])

        mock_session = MagicMock()
        mock_session.get.return_value.__aenter__.return_value = mock_response
        adapter._session = mock_session

        states = await adapter.get_states()

        assert len(states) == 2
        assert states[0].entity_id == "light.living_room"
        assert states[0].state == "on"
        assert states[1].entity_id == "switch.garage"

    @pytest.mark.asyncio
    async def test_get_state_success(self, adapter):
        """Test successful get_state."""
        adapter._connected = True
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "entity_id": "light.living_room",
            "state": "on",
            "attributes": {"brightness": 255},
            "last_changed": "",
            "last_updated": "",
        })

        mock_session = MagicMock()
        mock_session.get.return_value.__aenter__.return_value = mock_response
        adapter._session = mock_session

        entity = await adapter.get_state("light.living_room")

        assert entity.entity_id == "light.living_room"
        assert entity.state == "on"
        assert entity.attributes["brightness"] == 255

    @pytest.mark.asyncio
    async def test_get_state_not_found(self, adapter):
        """Test get_state with 404."""
        adapter._connected = True
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.text = AsyncMock(return_value="Entity not found")

        mock_session = MagicMock()
        mock_session.get.return_value.__aenter__.return_value = mock_response
        adapter._session = mock_session

        with pytest.raises(HomeAssistantAPIError, match="Entity not found"):
            await adapter.get_state("light.nonexistent")

    @pytest.mark.asyncio
    async def test_call_service_not_connected(self, adapter):
        """Test call_service when not connected."""
        with pytest.raises(HomeAssistantConnectionError, match="Not connected"):
            await adapter.call_service("light", "turn_on")

    @pytest.mark.asyncio
    async def test_call_service_success(self, adapter):
        """Test successful call_service."""
        adapter._connected = True
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=[{"entity_id": "light.living_room"}])

        mock_session = MagicMock()
        mock_session.post.return_value.__aenter__.return_value = mock_response
        adapter._session = mock_session

        result = await adapter.call_service(
            "light",
            "turn_on",
            {"entity_id": "light.living_room"},
        )

        assert len(result) == 1
        assert result[0]["entity_id"] == "light.living_room"

    @pytest.mark.asyncio
    async def test_call_service_error(self, adapter):
        """Test call_service with error."""
        adapter._connected = True
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Invalid service data")

        mock_session = MagicMock()
        mock_session.post.return_value.__aenter__.return_value = mock_response
        adapter._session = mock_session

        with pytest.raises(HomeAssistantAPIError, match="Invalid service data"):
            await adapter.call_service("light", "invalid_service", {})

    @pytest.mark.asyncio
    async def test_list_services_success(self, adapter):
        """Test successful list_services."""
        adapter._connected = True
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "light": {"turn_on": {"description": "Turn on light"}},
            "switch": {"turn_on": {"description": "Turn on switch"}},
        })

        mock_session = MagicMock()
        mock_session.get.return_value.__aenter__.return_value = mock_response
        adapter._session = mock_session

        services = await adapter.list_services()

        assert "light.turn_on" in services
        assert services["light.turn_on"].domain == "light"

    @pytest.mark.asyncio
    async def test_listen_events(self, adapter):
        """Test event listening."""
        adapter._connected = True
        adapter._session = MagicMock()
        adapter._event_stream_task = None

        async def callback(event):
            pass

        listener_id = await adapter.listen_events("state_changed", callback)

        assert listener_id.startswith("listener_")
        assert "state_changed" in adapter._event_handlers

    @pytest.mark.asyncio
    async def test_fire_event_success(self, adapter):
        """Test firing an event."""
        adapter._connected = True
        mock_response = AsyncMock()
        mock_response.status = 200

        mock_session = MagicMock()
        mock_session.post.return_value.__aenter__.return_value = mock_response
        adapter._session = mock_session

        await adapter.fire_event("test_event", {"data": "value"})

        mock_session.post.assert_called_once()

    def test_unlisten_events(self, adapter):
        """Test unlisten events."""
        async def callback(event):
            pass

        adapter._event_handlers["state_changed"] = [callback]
        listener_id = "listener_state_changed_123"

        adapter.unlisten_events(listener_id)

        assert len(adapter._event_handlers["state_changed"]) == 0


class TestHomeAssistantErrors:
    """Tests for Home Assistant error classes."""

    def test_adapter_error(self):
        """Test base adapter error."""
        with pytest.raises(HomeAssistantAdapterError):
            raise HomeAssistantAdapterError("Test error")

    def test_connection_error(self):
        """Test connection error inherits from adapter error."""
        with pytest.raises(HomeAssistantAdapterError):
            raise HomeAssistantConnectionError("Connection failed")

    def test_api_error(self):
        """Test API error inherits from adapter error."""
        with pytest.raises(HomeAssistantAdapterError):
            raise HomeAssistantAPIError("API failed")