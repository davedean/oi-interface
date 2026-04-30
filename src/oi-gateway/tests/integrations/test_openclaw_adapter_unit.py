from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import aiohttp
import pytest

from integrations.openclaw_adapter import (
    HTTPOpenClawConnection,
    OpenClawAdapter,
    OpenClawConnectionError,
    OpenClawRequestError,
    OpenClawResponse,
    OpenClawTimeoutError,
)


class AsyncResponse:
    def __init__(self, *, status: int = 200, json_data=None, text_data: str = ""):
        self.status = status
        self._json_data = json_data
        self._text_data = text_data

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
        self.get = MagicMock()
        self.post = MagicMock()
        self.closed = False

    async def close(self):
        self.closed = True


@pytest.fixture
def connection():
    return HTTPOpenClawConnection("http://localhost:8080", api_key="key", timeout=10.0)


@pytest.mark.asyncio
async def test_connect_success_and_root_fallback(connection):
    session = SessionStub()
    session.get.side_effect = [AsyncResponse(status=200)]
    with patch("aiohttp.ClientSession", return_value=session):
        assert await connection.connect() is True
    assert connection.is_connected is True

    connection = HTTPOpenClawConnection("http://localhost:8080", api_key="key", timeout=10.0)
    session = SessionStub()
    session.get.side_effect = [AsyncResponse(status=404), AsyncResponse(status=200)]
    with patch("aiohttp.ClientSession", return_value=session):
        assert await connection.connect() is True


@pytest.mark.asyncio
async def test_connect_failure_paths(connection):
    session = SessionStub()
    session.get.side_effect = [AsyncResponse(status=500)]
    with patch("aiohttp.ClientSession", return_value=session):
        assert await connection.connect() is False

    session = SessionStub()
    session.get.side_effect = aiohttp.ClientError("down")
    with patch("aiohttp.ClientSession", return_value=session):
        assert await connection.connect() is False


@pytest.mark.asyncio
async def test_disconnect_cancels_pending_futures(connection):
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    connection._session = SessionStub()
    connection._connected = True
    connection._pending_responses = {"1": fut}
    await connection.disconnect()
    assert fut.result().error == "Connection closed"
    assert connection._pending_responses == {}
    assert connection.is_connected is False


@pytest.mark.asyncio
async def test_send_message_error_and_connection_paths(connection):
    with pytest.raises(OpenClawConnectionError, match="Not connected"):
        await connection.send_message("x", {})

    connection._connected = True
    session = SessionStub()
    session.post.return_value = AsyncResponse(status=400, text_data="bad")
    connection._session = session
    with pytest.raises(OpenClawRequestError, match="400: bad"):
        await connection.send_message("x", {})

    session = SessionStub()
    session.post.side_effect = aiohttp.ClientError("offline")
    connection._session = session
    with pytest.raises(OpenClawConnectionError, match="Failed to send message"):
        await connection.send_message("x", {})


@pytest.mark.asyncio
async def test_receive_response_variants(connection):
    connection._connected = True
    session = SessionStub()
    session.get.return_value = AsyncResponse(status=200, json_data={"status": "success", "data": {"x": 1}, "request_id": "1"})
    connection._session = session
    response = await connection.receive_response()
    assert response == OpenClawResponse(status="success", data={"x": 1}, error=None, request_id="1")

    session = SessionStub()
    session.get.return_value = AsyncResponse(status=204)
    connection._session = session
    assert await connection.receive_response() is None

    session = SessionStub()
    session.get.return_value = AsyncResponse(status=500)
    connection._session = session
    assert await connection.receive_response() is None

    session = SessionStub()
    session.get.side_effect = asyncio.TimeoutError()
    connection._session = session
    with pytest.raises(OpenClawTimeoutError):
        await connection.receive_response()

    session = SessionStub()
    session.get.side_effect = aiohttp.ClientError("offline")
    connection._session = session
    with pytest.raises(OpenClawConnectionError, match="Failed to receive response"):
        await connection.receive_response()


@pytest.mark.asyncio
async def test_adapter_wrapper_methods():
    adapter = OpenClawAdapter("http://localhost:8080", api_key="key")
    with patch.object(adapter._connection, "connect", return_value=True):
        assert await adapter.connect() is True
    with patch.object(adapter._connection, "disconnect") as mock_disconnect:
        await adapter.disconnect()
        mock_disconnect.assert_awaited_once()
    with patch.object(adapter._connection, "send_message", return_value=OpenClawResponse(status="success", data={"task_id": "1"})) as mock_send:
        assert (await adapter.execute_task("task", {"a": 1})).data == {"task_id": "1"}
        assert (await adapter.query_status()).status == "success"
        assert await adapter.list_capabilities() == []
    assert adapter.base_url == "http://localhost:8080"
