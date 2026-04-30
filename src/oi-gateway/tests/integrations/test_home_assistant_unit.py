from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from integrations.home_assistant import (
    HAEvent,
    HomeAssistantAdapter,
    HomeAssistantAPIError,
    HomeAssistantConnectionError,
)


class AsyncResponse:
    def __init__(self, *, status: int = 200, json_data=None, text_data: str = "", content=None):
        self.status = status
        self._json_data = json_data
        self._text_data = text_data
        self.content = content or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data


class SessionStub:
    def __init__(self):
        self.closed = False
        self.get = MagicMock()
        self.post = MagicMock()

    async def close(self):
        self.closed = True


class AsyncBytesIter:
    def __init__(self, chunks):
        self._iter = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


@pytest.fixture
def adapter():
    return HomeAssistantAdapter("http://homeassistant:8123", "token")


@pytest.mark.asyncio
async def test_connect_success_sets_connected(adapter):
    session = SessionStub()
    session.get.return_value = AsyncResponse(status=200)
    with patch("aiohttp.ClientSession", return_value=session):
        assert await adapter.connect() is True
    assert adapter.is_connected is True
    assert adapter.base_url == "http://homeassistant:8123"


@pytest.mark.asyncio
async def test_connect_handles_non_200_and_client_error(adapter):
    session = SessionStub()
    session.get.return_value = AsyncResponse(status=401)
    with patch("aiohttp.ClientSession", return_value=session):
        assert await adapter.connect() is False
    session = SessionStub()
    session.get.side_effect = aiohttp.ClientError("nope")
    with patch("aiohttp.ClientSession", return_value=session):
        assert await adapter.connect() is False


@pytest.mark.asyncio
async def test_disconnect_cancels_stream_and_clears_handlers(adapter):
    adapter._session = SessionStub()
    adapter._connected = True
    adapter._event_handlers = {"state_changed": [AsyncMock()]}
    adapter._event_stream_task = asyncio.create_task(asyncio.sleep(10))
    await adapter.disconnect()
    assert adapter._session is None
    assert adapter._connected is False
    assert adapter._event_handlers == {}
    assert adapter._event_stream_task is None


@pytest.mark.asyncio
async def test_get_states_success_and_error_paths(adapter):
    adapter._connected = True
    session = SessionStub()
    session.get.return_value = AsyncResponse(status=200, json_data=[{"entity_id": "light.kitchen", "state": "on"}])
    adapter._session = session
    states = await adapter.get_states()
    assert states[0].entity_id == "light.kitchen"
    assert states[0].attributes == {}

    session = SessionStub()
    session.get.return_value = AsyncResponse(status=500, text_data="bad")
    adapter._session = session
    with pytest.raises(HomeAssistantAPIError, match="500: bad"):
        await adapter.get_states()

    session = SessionStub()
    session.get.side_effect = aiohttp.ClientError("boom")
    adapter._session = session
    with pytest.raises(HomeAssistantConnectionError, match="Failed to get states"):
        await adapter.get_states()


@pytest.mark.asyncio
async def test_get_state_success_and_error_paths(adapter):
    adapter._connected = True
    session = SessionStub()
    session.get.return_value = AsyncResponse(status=200, json_data={"entity_id": "light.kitchen", "state": "on"})
    adapter._session = session
    state = await adapter.get_state("light.kitchen")
    assert state.last_changed == ""
    assert state.last_updated == ""

    session = SessionStub()
    session.get.return_value = AsyncResponse(status=404)
    adapter._session = session
    with pytest.raises(HomeAssistantAPIError, match="Entity not found"):
        await adapter.get_state("light.missing")

    session = SessionStub()
    session.get.return_value = AsyncResponse(status=500, text_data="oops")
    adapter._session = session
    with pytest.raises(HomeAssistantAPIError, match="500: oops"):
        await adapter.get_state("light.bad")

    session = SessionStub()
    session.get.side_effect = aiohttp.ClientError("down")
    adapter._session = session
    with pytest.raises(HomeAssistantConnectionError, match="Failed to get state"):
        await adapter.get_state("light.bad")


@pytest.mark.asyncio
async def test_call_service_and_list_services_success_and_error_paths(adapter):
    adapter._connected = True
    session = SessionStub()
    session.post.return_value = AsyncResponse(status=200, json_data={"ok": True})
    adapter._session = session
    assert await adapter.call_service("light", "turn_on") == {"ok": True}

    session = SessionStub()
    session.post.return_value = AsyncResponse(status=400, text_data="bad service")
    adapter._session = session
    with pytest.raises(HomeAssistantAPIError, match="bad service"):
        await adapter.call_service("light", "turn_on", {})

    session = SessionStub()
    session.post.side_effect = aiohttp.ClientError("offline")
    adapter._session = session
    with pytest.raises(HomeAssistantConnectionError, match="Failed to call service"):
        await adapter.call_service("light", "turn_on", {})

    session = SessionStub()
    session.get.return_value = AsyncResponse(status=200, json_data={"light": {"turn_on": {"description": "Turn on"}}})
    adapter._session = session
    services = await adapter.list_services()
    assert services["light.turn_on"].service == "turn_on"

    session = SessionStub()
    session.get.return_value = AsyncResponse(status=500, text_data="bad services")
    adapter._session = session
    with pytest.raises(HomeAssistantAPIError, match="500: bad services"):
        await adapter.list_services()

    session = SessionStub()
    session.get.side_effect = aiohttp.ClientError("offline")
    adapter._session = session
    with pytest.raises(HomeAssistantConnectionError, match="Failed to list services"):
        await adapter.list_services()


@pytest.mark.asyncio
async def test_fire_event_success_and_error_paths(adapter):
    adapter._connected = True
    session = SessionStub()
    session.post.return_value = AsyncResponse(status=200)
    adapter._session = session
    await adapter.fire_event("x", {})

    session = SessionStub()
    session.post.return_value = AsyncResponse(status=500, text_data="nope")
    adapter._session = session
    with pytest.raises(HomeAssistantAPIError, match="Failed to fire event: nope"):
        await adapter.fire_event("x", {})

    session = SessionStub()
    session.post.side_effect = aiohttp.ClientError("offline")
    adapter._session = session
    with pytest.raises(HomeAssistantConnectionError, match="Failed to fire event"):
        await adapter.fire_event("x", {})


@pytest.mark.asyncio
async def test_listen_and_unlisten_events(adapter):
    adapter._connected = True
    adapter._session = SessionStub()
    called = []

    async def handler(event: HAEvent):
        called.append(event.event_type)

    listener_id = await adapter.listen_events("state_changed", handler)
    assert listener_id.startswith("listener_state_changed_")
    adapter.unlisten_events(listener_id)
    assert adapter._event_handlers["state_changed"] == []
    await adapter.disconnect()
    assert called == []


@pytest.mark.asyncio
async def test_event_stream_dispatches_specific_and_all_handlers(adapter):
    adapter._connected = True
    session = SessionStub()
    session.get.return_value = AsyncResponse(
        status=200,
        content=AsyncBytesIter([
            b":ignore\n",
            b"data:{\"event_type\":\"state_changed\",\"data\":{\"entity_id\":\"light.kitchen\"},\"origin\":\"LOCAL\",\"time_fired\":\"now\"}\n",
            b"data:not-json\n",
        ]),
    )
    adapter._session = session
    seen = []

    async def specific(event: HAEvent):
        seen.append(("specific", event.data["entity_id"]))

    async def all_handler(event: HAEvent):
        seen.append(("all", event.event_type))

    adapter._event_handlers = {"state_changed": [specific], None: [all_handler]}
    await adapter._event_stream()
    assert seen == [("specific", "light.kitchen"), ("all", "state_changed")]


@pytest.mark.asyncio
async def test_event_stream_handles_handler_exception_and_non_200(adapter, caplog):
    adapter._connected = True
    session = SessionStub()
    session.get.return_value = AsyncResponse(
        status=200,
        content=AsyncBytesIter([
            b"data:{\"event_type\":\"state_changed\",\"data\":{},\"origin\":\"LOCAL\",\"time_fired\":\"now\"}\n",
        ]),
    )
    adapter._session = session

    async def broken(event: HAEvent):
        raise RuntimeError("bad handler")

    adapter._event_handlers = {"state_changed": [broken]}
    caplog.set_level("ERROR")
    await adapter._event_stream()
    assert "Error in event handler" in caplog.text

    session = SessionStub()
    session.get.return_value = AsyncResponse(status=503)
    adapter._session = session
    caplog.set_level("WARNING")
    await adapter._event_stream()
    assert "Event stream returned status 503" in caplog.text


@pytest.mark.asyncio
async def test_event_stream_returns_without_session_or_on_cancel(adapter, caplog):
    adapter._session = None
    await adapter._event_stream()

    class CancelSession(SessionStub):
        def __init__(self):
            super().__init__()
            self.get.side_effect = asyncio.CancelledError()

    adapter._session = CancelSession()
    caplog.set_level("INFO")
    await adapter._event_stream()
    assert "Event stream cancelled" in caplog.text
