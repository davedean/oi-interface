"""Tests for OpenClaw adapter."""
from __future__ import annotations
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientError, web

# Skip unless explicitly enabled (requires running OpenClaw server)
pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_OPENCLAW_TESTS"),
    reason="Requires running OpenClaw server. Set RUN_OPENCLAW_TESTS=1 to enable."
)

from integrations.openclaw_adapter import (
    HTTPOpenClawConnection,
    OpenClawAdapter,
    OpenClawAdapterError,
    OpenClawConnectionError,
    OpenClawRequestError,
    OpenClawResponse,
)


class TestOpenClawResponse:
    """Tests for OpenClawResponse dataclass."""

    def test_response_success(self):
        """Test successful response creation."""
        response = OpenClawResponse(
            status="success",
            data={"result": "ok"},
            request_id="123",
        )
        assert response.status == "success"
        assert response.data == {"result": "ok"}
        assert response.request_id == "123"
        assert response.error is None

    def test_response_error(self):
        """Test error response creation."""
        response = OpenClawResponse(
            status="error",
            error="Something went wrong",
            request_id="456",
        )
        assert response.status == "error"
        assert response.error == "Something went wrong"
        assert response.data is None


class TestHTTPOpenClawConnection:
    """Tests for HTTPOpenClawConnection."""

    @pytest.fixture
    def connection(self):
        """Create a connection instance."""
        return HTTPOpenClawConnection(
            base_url="http://localhost:8080",
            api_key="test-key",
            timeout=10.0,
        )

    def test_init(self, connection):
        """Test connection initialization."""
        assert connection._base_url == "http://localhost:8080"
        assert connection._api_key == "test-key"
        assert connection._connected is False

    def test_get_headers_with_api_key(self, connection):
        """Test headers with API key."""
        headers = connection._get_headers()
        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == "Bearer test-key"

    def test_get_headers_without_api_key(self):
        """Test headers without API key."""
        connection = HTTPOpenClawConnection(base_url="http://localhost:8080")
        headers = connection._get_headers()
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_connect_success(self, connection):
        """Test successful connection."""
        mock_response = AsyncMock()
        mock_response.status = 200

        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response

            result = await connection.connect()
            assert result is True
            assert connection._connected is True

    @pytest.mark.asyncio
    async def test_connect_failure(self, connection):
        """Test failed connection."""
        with patch("aiohttp.ClientSession") as mock_session:
            mock_session.return_value.__aenter__.return_value.get.side_effect = ClientError("Connection refused")

            result = await connection.connect()
            assert result is False
            assert connection._connected is False

    @pytest.mark.asyncio
    async def test_disconnect(self, connection):
        """Test disconnection."""
        connection._session = MagicMock()
        connection._connected = True

        await connection.disconnect()

        assert connection._session is None
        assert connection._connected is False

    @pytest.mark.asyncio
    async def test_send_message_not_connected(self, connection):
        """Test sending message when not connected."""
        with pytest.raises(OpenClawConnectionError, match="Not connected"):
            await connection.send_message("test_action", {})

    @pytest.mark.asyncio
    async def test_send_message_success(self, connection):
        """Test successful message sending."""
        connection._connected = True
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "status": "success",
            "data": {"result": "ok"},
            "request_id": "1",
        })

        mock_session = MagicMock()
        mock_session.post.return_value.__aenter__.return_value = mock_response
        connection._session = mock_session

        response = await connection.send_message("test_action", {"key": "value"})

        assert response.status == "success"
        assert response.data == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_send_message_error_status(self, connection):
        """Test message sending with error status."""
        connection._connected = True
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Bad Request")

        mock_session = MagicMock()
        mock_session.post.return_value.__aenter__.return_value = mock_response
        connection._session = mock_session

        with pytest.raises(OpenClawRequestError):
            await connection.send_message("test_action", {})


class TestOpenClawAdapter:
    """Tests for OpenClawAdapter."""

    @pytest.fixture
    def adapter(self):
        """Create an adapter instance."""
        return OpenClawAdapter(
            base_url="http://localhost:8080",
            api_key="test-key",
        )

    def test_init(self, adapter):
        """Test adapter initialization."""
        assert adapter.base_url == "http://localhost:8080"

    @pytest.mark.asyncio
    async def test_connect(self, adapter):
        """Test connect method."""
        with patch.object(adapter._connection, "connect", return_value=True):
            result = await adapter.connect()
            assert result is True

    @pytest.mark.asyncio
    async def test_disconnect(self, adapter):
        """Test disconnect method."""
        await adapter.disconnect()
        assert adapter.is_connected is False

    @pytest.mark.asyncio
    async def test_send_message(self, adapter):
        """Test send_message method."""
        with patch.object(adapter._connection, "send_message", return_value=OpenClawResponse(status="success")):
            response = await adapter.send_message("test", {})
            assert response.status == "success"

    @pytest.mark.asyncio
    async def test_execute_task(self, adapter):
        """Test execute_task method."""
        with patch.object(adapter._connection, "send_message", return_value=OpenClawResponse(status="success", data={"task_id": "123"})) as mock_send:
            response = await adapter.execute_task("test_task", {"param": "value"})
            mock_send.assert_called_once_with("execute_task", {"task": "test_task", "params": {"param": "value"}})
            assert response.status == "success"

    @pytest.mark.asyncio
    async def test_query_status(self, adapter):
        """Test query_status method."""
        with patch.object(adapter._connection, "send_message", return_value=OpenClawResponse(status="success", data={"status": "ready"})) as mock_send:
            response = await adapter.query_status()
            mock_send.assert_called_once_with("status", {})
            assert response.status == "success"

    @pytest.mark.asyncio
    async def test_list_capabilities(self, adapter):
        """Test list_capabilities method."""
        with patch.object(adapter._connection, "send_message", return_value=OpenClawResponse(status="success", data={"capabilities": ["cap1", "cap2"]})) as mock_send:
            caps = await adapter.list_capabilities()
            mock_send.assert_called_once_with("capabilities", {})
            assert caps == ["cap1", "cap2"]

    @pytest.mark.asyncio
    async def test_list_capabilities_empty(self, adapter):
        """Test list_capabilities with no capabilities."""
        with patch.object(adapter._connection, "send_message", return_value=OpenClawResponse(status="success", data=None)) as mock_send:
            caps = await adapter.list_capabilities()
            assert caps == []


class TestOpenClawErrors:
    """Tests for OpenClaw error classes."""

    def test_adapter_error(self):
        """Test base adapter error."""
        with pytest.raises(OpenClawAdapterError):
            raise OpenClawAdapterError("Test error")

    def test_connection_error(self):
        """Test connection error inherits from adapter error."""
        with pytest.raises(OpenClawAdapterError):
            raise OpenClawConnectionError("Connection failed")

    def test_request_error(self):
        """Test request error inherits from adapter error."""
        with pytest.raises(OpenClawAdapterError):
            raise OpenClawRequestError("Request failed")