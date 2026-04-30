"""Tests for Hermes adapter."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations import hermes_adapter

# Skip all tests if paho-mqtt is not installed
pytestmark = pytest.mark.skipif(
    not hermes_adapter.HAS_PAHO,
    reason="paho-mqtt not installed. Install with: pip install paho-mqtt"
)

from integrations.hermes_adapter import (
    HermesAdapterError,
    HermesConnectionError,
    HermesIntent,
    HermesMessage,
    HermesMQTTAdapter,
    HermesPublishError,
    HermesSubscribeError,
)


class TestHermesMessage:
    """Tests for HermesMessage dataclass."""

    def test_message_creation(self):
        """Test message creation."""
        message = HermesMessage(
            topic="hermes/intent/test",
            payload={"intent": {"intentName": "testIntent"}},
            site_id="living_room",
        )
        assert message.topic == "hermes/intent/test"
        assert message.payload["intent"]["intentName"] == "testIntent"
        assert message.site_id == "living_room"


class TestHermesIntent:
    """Tests for HermesIntent dataclass."""

    def test_intent_creation(self):
        """Test intent creation."""
        intent = HermesIntent(
            intent_name="TurnOnLight",
            slots={"light": "living room"},
            site_id="living_room",
            session_id="session-123",
        )
        assert intent.intent_name == "TurnOnLight"
        assert intent.slots["light"] == "living room"
        assert intent.site_id == "living_room"
        assert intent.session_id == "session-123"


class TestHermesMQTTAdapter:
    """Tests for HermesMQTTAdapter."""

    @pytest.fixture
    def adapter(self):
        """Create an adapter instance."""
        return HermesMQTTAdapter(
            mqtt_host="localhost",
            mqtt_port=1883,
            mqtt_username="user",
            mqtt_password="pass",
            site_id="default",
        )

    def test_init(self, adapter):
        """Test adapter initialization."""
        assert adapter._mqtt_host == "localhost"
        assert adapter._mqtt_port == 1883
        assert adapter._site_id == "default"
        assert adapter._connected is False

    @pytest.mark.asyncio
    async def test_connect_success(self, adapter):
        """Test successful connection."""
        mock_client = MagicMock()
        mock_client.subscribe = MagicMock(return_value=(0, None))

        with patch("paho.mqtt.client.Client") as mock_client_class:
            mock_client_class.return_value = mock_client
            # Mock the on_connect callback to set connected = True
            def set_connected(*args):
                adapter._connected = True

            mock_client.on_connect = set_connected

            # We need to mock the connection to succeed
            with patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
                mock_client.connect.return_value = None
                mock_client.loop_start.return_value = None

                # Manually set connected for test
                adapter._connected = True

                result = await adapter.connect()
                assert result is True

    @pytest.mark.asyncio
    async def test_disconnect(self, adapter):
        """Test disconnection."""
        adapter._client = MagicMock()

        await adapter.disconnect()

        assert adapter._connected is False

    @pytest.mark.asyncio
    async def test_subscribe_not_connected(self, adapter):
        """Test subscribing when not connected."""
        with pytest.raises(HermesConnectionError, match="Not connected"):
            await adapter.subscribe("hermes/intent/#")

    @pytest.mark.asyncio
    async def test_subscribe_success(self, adapter):
        """Test successful subscription."""
        adapter._connected = True
        adapter._client = MagicMock()
        adapter._client.subscribe = MagicMock(return_value=(0, None))

        result = await adapter.subscribe("hermes/intent/#")

        assert result is True
        adapter._client.subscribe.assert_called_once_with("hermes/intent/#", qos=1)

    @pytest.mark.asyncio
    async def test_subscribe_failure(self, adapter):
        """Test failed subscription."""
        adapter._connected = True
        adapter._client = MagicMock()
        adapter._client.subscribe = MagicMock(return_value=(1, "Error"))

        with pytest.raises(HermesSubscribeError):
            await adapter.subscribe("hermes/intent/#")

    @pytest.mark.asyncio
    async def test_publish_not_connected(self, adapter):
        """Test publishing when not connected."""
        with pytest.raises(HermesConnectionError, match="Not connected"):
            await adapter.publish("hermes/tts/say", {"text": "Hello"})

    @pytest.mark.asyncio
    async def test_publish_success(self, adapter):
        """Test successful publish."""
        adapter._connected = True
        adapter._client = MagicMock()
        adapter._client.publish = MagicMock(return_value=(0, None))

        result = await adapter.publish(
            "hermes/tts/say",
            {"text": "Hello", "siteId": "default"},
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_publish_failure(self, adapter):
        """Test failed publish."""
        adapter._connected = True
        adapter._client = MagicMock()
        adapter._client.publish = MagicMock(return_value=(1, "Error"))

        with pytest.raises(HermesPublishError):
            await adapter.publish("hermes/tts/say", {"text": "Hello"})

    @pytest.mark.asyncio
    async def test_speak(self, adapter):
        """Test speak method."""
        adapter._connected = True
        adapter._client = MagicMock()
        adapter._client.publish = MagicMock(return_value=(0, None))

        result = await adapter.speak("Hello world")

        assert result is True
        call_args = adapter._client.publish.call_args
        assert call_args[0][0] == "hermes/tts/say"
        payload = json.loads(call_args[0][1])
        assert payload["text"] == "Hello world"
        assert payload["siteId"] == "default"

    @pytest.mark.asyncio
    async def test_startListening(self, adapter):
        """Test startListening method."""
        adapter._connected = True
        adapter._client = MagicMock()
        adapter._client.publish = MagicMock(return_value=(0, None))

        result = await adapter.startListening()

        assert result is True
        call_args = adapter._client.publish.call_args
        assert call_args[0][0] == "hermes/dialogueManager/startListening"

    @pytest.mark.asyncio
    async def test_endSession(self, adapter):
        """Test endSession method."""
        adapter._connected = True
        adapter._client = MagicMock()
        adapter._client.publish = MagicMock(return_value=(0, None))

        result = await adapter.endSession("session-123", "Goodbye")

        assert result is True
        call_args = adapter._client.publish.call_args
        payload = json.loads(call_args[0][1])
        assert payload["sessionId"] == "session-123"
        assert payload["text"] == "Goodbye"

    def test_register_handler(self, adapter):
        """Test handler registration."""
        async def handler(msg):
            pass

        adapter.register_handler("hermes/intent/#", handler)

        assert "hermes/intent/#" in adapter._message_handlers

    def test_unregister_handler(self, adapter):
        """Test handler unregistration."""
        async def handler(msg):
            pass

        adapter.register_handler("hermes/intent/#", handler)
        adapter.unregister_handler("hermes/intent/#")

        assert "hermes/intent/#" not in adapter._message_handlers

    @pytest.mark.asyncio
    async def test_handle_message(self, adapter):
        """Test message handling."""
        message = HermesMessage(
            topic="hermes/intent/test",
            payload={"intent": {"intentName": "test"}},
        )

        async def handler(msg):
            pass

        adapter.register_handler("hermes/intent/#", handler)

        await adapter.handle_message(message)

    @pytest.mark.asyncio
    async def test_listen_intents(self, adapter):
        """Test intent listening."""
        adapter._connected = True
        adapter._client = MagicMock()
        adapter._client.subscribe = MagicMock(return_value=(0, None))

        async def callback(intent):
            pass

        await adapter.listen_intents(callback)

        assert "hermes/intent/#" in adapter._message_handlers

    def test_match_topic(self, adapter):
        """Test topic matching."""
        assert adapter._match_topic("hermes/intent/turnOn", "hermes/intent/#")
        assert adapter._match_topic("hermes/tts/say", "hermes/tts/#")
        assert not adapter._match_topic("other/topic", "hermes/intent/#")


class TestHermesErrors:
    """Tests for Hermes error classes."""

    def test_adapter_error(self):
        """Test base adapter error."""
        with pytest.raises(HermesAdapterError):
            raise HermesAdapterError("Test error")

    def test_connection_error(self):
        """Test connection error inherits from adapter error."""
        with pytest.raises(HermesAdapterError):
            raise HermesConnectionError("Connection failed")

    def test_publish_error(self):
        """Test publish error inherits from adapter error."""
        with pytest.raises(HermesAdapterError):
            raise HermesPublishError("Publish failed")

    def test_subscribe_error(self):
        """Test subscribe error inherits from adapter error."""
        with pytest.raises(HermesAdapterError):
            raise HermesSubscribeError("Subscribe failed")


# Need json for some tests
import json