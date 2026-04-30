from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations import hermes_adapter as module
from integrations.hermes_adapter import (
    HermesConnectionError,
    HermesDependencyError,
    HermesIntent,
    HermesMessage,
    HermesMQTTAdapter,
    HermesPublishError,
    HermesSubscribeError,
)


class FakeMQTT:
    MQTT_ERR_SUCCESS = 0

    class Client:
        def __init__(self, client_id=None):
            self.client_id = client_id
            self.username_pw_set = MagicMock()
            self.connect = MagicMock()
            self.loop_start = MagicMock()
            self.loop_stop = MagicMock()
            self.disconnect = MagicMock()
            self.subscribe = MagicMock(return_value=(0, None))
            self.publish = MagicMock(return_value=(0, None))
            self.on_connect = None
            self.on_disconnect = None
            self.on_message = None


@pytest.fixture
def adapter():
    return HermesMQTTAdapter("localhost", 1883, "user", "pass", "site-a")


@pytest.mark.asyncio
async def test_connect_raises_without_paho(adapter):
    with patch.object(module, "HAS_PAHO", False):
        with pytest.raises(HermesDependencyError):
            await adapter.connect()


@pytest.mark.asyncio
async def test_connect_success_timeout_and_exception_paths(adapter):
    fake_mqtt = FakeMQTT()
    with patch.object(module, "HAS_PAHO", True), patch.object(module, "mqtt", fake_mqtt), patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
        async def fast_wait_for(fut, timeout):
            adapter._connected = True
            fut.set_result(0)
            return await fut

        with patch("asyncio.wait_for", side_effect=fast_wait_for):
            assert await adapter.connect() is True
        assert adapter.is_connected is True
        assert adapter._client.client_id == "oi-gateway-site-a"
        adapter._client.username_pw_set.assert_called_once_with("user", "pass")

    adapter = HermesMQTTAdapter("localhost", 1883, site_id="site-b")
    with patch.object(module, "HAS_PAHO", True), patch.object(module, "mqtt", fake_mqtt), patch("asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)), patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        assert await adapter.connect() is False

    adapter = HermesMQTTAdapter("localhost", 1883, site_id="site-c")
    with patch.object(module, "HAS_PAHO", True), patch.object(module, "mqtt", fake_mqtt), patch("asyncio.to_thread", side_effect=RuntimeError("boom")):
        assert await adapter.connect() is False


@pytest.mark.asyncio
async def test_disconnect_handles_exception(adapter):
    adapter._client = FakeMQTT.Client()
    adapter._client.loop_stop.side_effect = RuntimeError("bad stop")
    await adapter.disconnect()
    assert adapter.is_connected is False
    assert adapter._client is None


@pytest.mark.asyncio
async def test_subscribe_and_publish_error_paths(adapter):
    with pytest.raises(HermesConnectionError):
        await adapter.subscribe("hermes/intent/#")
    with pytest.raises(HermesConnectionError):
        await adapter.publish("hermes/tts/say", {"text": "x"})

    fake_mqtt = FakeMQTT()
    adapter._connected = True
    adapter._client = fake_mqtt.Client()
    adapter._client.subscribe.return_value = (1, None)
    with pytest.raises(HermesSubscribeError, match="MQTT subscribe failed"):
        await adapter.subscribe("hermes/intent/#")
    adapter._client.subscribe.side_effect = RuntimeError("boom")
    with pytest.raises(HermesSubscribeError, match="Failed to subscribe"):
        await adapter.subscribe("hermes/intent/#")

    adapter._client = fake_mqtt.Client()
    adapter._client.publish.return_value = (1, None)
    with pytest.raises(HermesPublishError, match="MQTT publish failed"):
        await adapter.publish("hermes/tts/say", {"text": "x"})
    adapter._client.publish.side_effect = RuntimeError("boom")
    with pytest.raises(HermesPublishError, match="Failed to publish"):
        await adapter.publish("hermes/tts/say", {"text": "x"})


@pytest.mark.asyncio
async def test_listen_intents_and_message_handling(adapter):
    adapter.subscribe = AsyncMock(return_value=True)
    received: list[HermesIntent] = []

    async def callback(intent: HermesIntent):
        received.append(intent)

    await adapter.listen_intents(callback)
    assert "hermes/intent/#" in adapter._message_handlers
    adapter.subscribe.assert_awaited_once_with("hermes/intent/#")

    await adapter.handle_message(HermesMessage(
        topic="hermes/intent/TurnOn",
        payload={"intent": {"intentName": "TurnOn"}, "slots": {"room": "kitchen"}, "siteId": "satellite", "sessionId": "s1"},
    ))
    assert received == [HermesIntent("TurnOn", {"room": "kitchen"}, "satellite", "s1")]

    async def broken(_message):
        raise RuntimeError("handler boom")

    adapter.register_handler("hermes/tts/#", broken)
    await adapter.handle_message(HermesMessage(topic="hermes/tts/say", payload={}))
    adapter.unregister_handler("hermes/tts/#")
    assert "hermes/tts/#" not in adapter._message_handlers


@pytest.mark.asyncio
async def test_speak_start_listening_and_end_session(adapter):
    adapter.publish = AsyncMock(return_value=True)
    assert await adapter.speak("Hello") is True
    adapter.publish.assert_any_await("hermes/tts/say", {"text": "Hello", "siteId": "site-a"})

    assert await adapter.startListening("remote") is True
    adapter.publish.assert_any_await("hermes/dialogueManager/startListening", {"siteId": "remote"})

    assert await adapter.endSession("session-1", "Bye") is True
    adapter.publish.assert_any_await("hermes/dialogueManager/endSession", {"sessionId": "session-1", "text": "Bye"})

    assert await adapter.endSession("session-2") is True
    adapter.publish.assert_any_await("hermes/dialogueManager/endSession", {"sessionId": "session-2"})


def test_on_connect_disconnect_match_topic_and_on_message(adapter):
    adapter._on_connect(None, None, None, 0)
    assert adapter.is_connected is True
    adapter._on_connect(None, None, None, 5)
    adapter._on_disconnect(None, None, 1)
    assert adapter.is_connected is False

    assert adapter._match_topic("hermes/intent/turnOn", "hermes/intent/#") is True
    assert adapter._match_topic("hermes/audioServer/default/playBytes/abc", "hermes/audioServer/+/playBytes/#") is True
    assert adapter._match_topic("other/topic", "hermes/intent/#") is False

    loop = asyncio.new_event_loop()
    adapter._loop = loop
    adapter.handle_message = AsyncMock()
    scheduled = []

    def fake_run_coroutine_threadsafe(coro, target_loop):
        scheduled.append((coro, target_loop))
        coro.close()
        return SimpleNamespace()

    with patch("asyncio.run_coroutine_threadsafe", side_effect=fake_run_coroutine_threadsafe):
        msg = SimpleNamespace(topic="hermes/intent/test", payload=json.dumps({"siteId": "site-z"}).encode("utf-8"))
        adapter._on_message(None, None, msg)
        assert scheduled and scheduled[0][1] is loop

    bad = SimpleNamespace(topic="hermes/intent/test", payload=b"not-json")
    adapter._on_message(None, None, bad)
    loop.close()
