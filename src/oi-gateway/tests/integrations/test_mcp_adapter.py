"""Tests for the MCP adapter."""
from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


gateway_src = Path(__file__).parents[2] / "src"
if str(gateway_src) not in sys.path:
    sys.path.insert(0, str(gateway_src))

from integrations.mcp_adapter import (
    HTTPMCPClient,
    MCPAdapter,
    MCPConnectionError,
    MCPRequest,
    MCPRequestError,
    MCPResponse,
    StdioMCPClient,
)


class FakeProcess:
    def __init__(self, *, stdout_lines: list[bytes] | None = None, poll_result=None, wait_raises=False):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(b"".join(stdout_lines or []))
        self.stderr = io.BytesIO()
        self.returncode = poll_result
        self._poll_result = poll_result
        self._wait_raises = wait_raises
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._poll_result

    def wait(self, timeout=None):
        if self._wait_raises:
            import subprocess

            raise subprocess.TimeoutExpired("cmd", timeout)
        return 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class FakeResponse:
    def __init__(self, *, status=200, json_data=None):
        self.status = status
        self._json_data = json_data or {}

    async def json(self):
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self, *, get_response=None, post_response=None, get_exc=None, post_exc=None):
        self._get_response = get_response
        self._post_response = post_response
        self._get_exc = get_exc
        self._post_exc = post_exc
        self.get_calls = []
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        if self._get_exc:
            raise self._get_exc
        return self._get_response

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        if self._post_exc:
            raise self._post_exc
        return self._post_response


@pytest.mark.asyncio
async def test_stdio_client_connect_marks_connected(monkeypatch) -> None:
    process = FakeProcess(poll_result=None)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: process)

    client = StdioMCPClient(["fake-server"])
    assert await client.connect() is True
    assert client.is_connected is True


@pytest.mark.asyncio
async def test_stdio_client_connect_raises_when_process_exits(monkeypatch) -> None:
    process = FakeProcess(poll_result=2)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: process)

    client = StdioMCPClient(["fake-server"])

    with pytest.raises(MCPConnectionError, match="exited immediately"):
        await client.connect()


@pytest.mark.asyncio
async def test_stdio_client_disconnect_kills_hung_process() -> None:
    process = FakeProcess(wait_raises=True)
    client = StdioMCPClient(["fake-server"])
    client._process = process
    client._connected = True

    await client.disconnect()

    assert process.terminated is True
    assert process.killed is True
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_stdio_client_call_tool_sends_json_and_returns_result() -> None:
    response = b'{"jsonrpc":"2.0","id":"0","result":{"ok":true}}\n'
    process = FakeProcess(stdout_lines=[response], poll_result=None)
    client = StdioMCPClient(["fake-server"])
    client._process = process
    client._connected = True

    result = await client.call_tool("echo", {"text": "hi"})

    assert result == {"ok": True}
    request = process.stdin.getvalue().decode().strip()
    assert '"method": "tools/call"' in request
    assert '"name": "echo"' in request


@pytest.mark.asyncio
async def test_stdio_client_call_tool_raises_on_error_response() -> None:
    response = b'{"jsonrpc":"2.0","id":"0","error":{"message":"boom"}}\n'
    process = FakeProcess(stdout_lines=[response], poll_result=None)
    client = StdioMCPClient(["fake-server"])
    client._process = process
    client._connected = True

    with pytest.raises(MCPRequestError, match="boom"):
        await client.call_tool("echo", {})


@pytest.mark.asyncio
async def test_stdio_client_send_request_rejects_invalid_json() -> None:
    process = FakeProcess(stdout_lines=[b"not-json\n"], poll_result=None)
    client = StdioMCPClient(["fake-server"])
    client._process = process
    client._connected = True

    with pytest.raises(MCPRequestError, match="Invalid JSON"):
        await client._send_request(MCPRequest(id="1", method="tools/list"))


@pytest.mark.asyncio
async def test_stdio_client_send_request_requires_connection() -> None:
    client = StdioMCPClient(["fake-server"])

    with pytest.raises(MCPConnectionError, match="Not connected"):
        await client._send_request(MCPRequest(id="1", method="tools/list"))


@pytest.mark.asyncio
async def test_http_client_connect_success(monkeypatch) -> None:
    session = FakeSession(get_response=FakeResponse(status=200))
    monkeypatch.setattr("aiohttp.ClientSession", lambda: session)

    client = HTTPMCPClient("http://mcp.local/")
    assert await client.connect() is True
    assert client.is_connected is True
    assert session.get_calls[0][0] == "http://mcp.local/health"


@pytest.mark.asyncio
async def test_http_client_connect_failure_returns_false(monkeypatch) -> None:
    import aiohttp

    session = FakeSession(get_exc=aiohttp.ClientError("down"))
    monkeypatch.setattr("aiohttp.ClientSession", lambda: session)

    client = HTTPMCPClient("http://mcp.local")
    assert await client.connect() is False
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_http_client_call_tool_requires_connection() -> None:
    client = HTTPMCPClient("http://mcp.local")

    with pytest.raises(MCPConnectionError, match="Not connected"):
        await client.call_tool("echo", {})


@pytest.mark.asyncio
async def test_http_client_call_tool_handles_http_error_status(monkeypatch) -> None:
    session = FakeSession(post_response=FakeResponse(status=500, json_data={}))
    monkeypatch.setattr("aiohttp.ClientSession", lambda: session)

    client = HTTPMCPClient("http://mcp.local")
    client._connected = True

    with pytest.raises(MCPRequestError, match="status 500"):
        await client.call_tool("echo", {})


@pytest.mark.asyncio
async def test_http_client_call_tool_handles_rpc_error(monkeypatch) -> None:
    session = FakeSession(post_response=FakeResponse(status=200, json_data={"error": {"message": "bad"}}))
    monkeypatch.setattr("aiohttp.ClientSession", lambda: session)

    client = HTTPMCPClient("http://mcp.local")
    client._connected = True

    with pytest.raises(MCPRequestError, match="bad"):
        await client.call_tool("echo", {})


@pytest.mark.asyncio
async def test_http_client_call_method_returns_response(monkeypatch) -> None:
    session = FakeSession(post_response=FakeResponse(status=200, json_data={"jsonrpc": "2.0", "id": "1", "result": ["tool"]}))
    monkeypatch.setattr("aiohttp.ClientSession", lambda: session)

    client = HTTPMCPClient("http://mcp.local")
    client._connected = True

    response = await client.call_method("tools/list")

    assert isinstance(response, MCPResponse)
    assert response.result == ["tool"]


@pytest.mark.asyncio
async def test_http_client_call_method_wraps_client_error(monkeypatch) -> None:
    import aiohttp

    session = FakeSession(post_exc=aiohttp.ClientError("boom"))
    monkeypatch.setattr("aiohttp.ClientSession", lambda: session)

    client = HTTPMCPClient("http://mcp.local")
    client._connected = True

    with pytest.raises(MCPConnectionError, match="boom"):
        await client.call_method("tools/list")


@pytest.mark.asyncio
async def test_mcp_adapter_uses_transport_and_lists_tools() -> None:
    adapter = MCPAdapter(transport="http", url="http://mcp.local")
    adapter._client = MagicMock()
    adapter._client.call_method = AsyncMock(return_value=MCPResponse(result=[{"name": "echo"}]))

    tools = await adapter.list_tools()

    assert adapter.transport == "http"
    assert tools == [{"name": "echo"}]


@pytest.mark.asyncio
async def test_mcp_adapter_list_tools_raises_on_error() -> None:
    adapter = MCPAdapter(transport="http", url="http://mcp.local")
    adapter._client = MagicMock()
    adapter._client.call_method = AsyncMock(return_value=MCPResponse(error={"message": "nope"}))

    with pytest.raises(MCPRequestError, match="nope"):
        await adapter.list_tools()


def test_mcp_adapter_requires_valid_transport_configuration() -> None:
    with pytest.raises(ValueError, match="Invalid transport"):
        MCPAdapter(transport="tcp")
    with pytest.raises(ValueError, match="command required"):
        MCPAdapter(transport="stdio")
    with pytest.raises(ValueError, match="url required"):
        MCPAdapter(transport="http")
