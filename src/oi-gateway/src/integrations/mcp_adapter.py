"""MCP (Model Context Protocol) adapter for oi-gateway.

The MCP adapter allows oi-gateway to connect to MCP servers as a client,
enabling communication with any agent that exposes an MCP interface.

MCP uses JSON-RPC over stdio or HTTP. This adapter supports both modes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class MCPRequest:
    """An MCP request message."""
    jsonrpc: str = "2.0"
    id: str | None = None
    method: str = ""
    params: dict[str, Any] | None = None


@dataclass
class MCPResponse:
    """An MCP response message."""
    jsonrpc: str = "2.0"
    id: str | None = None
    result: Any = None
    error: dict[str, Any] | None = None


@runtime_checkable
class MCPClientProtocol(Protocol):
    """Protocol for MCP client implementations."""

    async def connect(self) -> bool:
        """Connect to the MCP server."""
        ...

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        ...

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server."""
        ...

    async def call_method(self, method: str, params: dict[str, Any] | None = None) -> MCPResponse:
        """Call a generic MCP method."""
        ...


class MCPAdapterError(Exception):
    """Error in MCP adapter."""
    pass


class MCPConnectionError(MCPAdapterError):
    """Failed to connect to MCP server."""
    pass


class MCPRequestError(MCPAdapterError):
    """MCP request failed."""
    pass


class StdioMCPClient:
    """MCP client that communicates over stdio with a subprocess.

    Parameters
    ----------
    command : list[str]
        Command to spawn the MCP server.
    """

    def __init__(self, command: list[str]) -> None:
        self._command = command
        self._process: subprocess.Popen | None = None
        self._request_id = 0
        self._connected = False

    async def connect(self) -> bool:
        """Start the MCP server subprocess and establish connection."""
        try:
            self._process = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            # Wait briefly for server to initialize
            await asyncio.sleep(0.1)
            if self._process.poll() is not None:
                raise MCPConnectionError(f"MCP server exited immediately: {self._process.returncode}")
            self._connected = True
            logger.info("Connected to MCP server: %s", " ".join(self._command))
            return True
        except FileNotFoundError as e:
            raise MCPConnectionError(f"MCP server command not found: {e}") from e
        except Exception as e:
            raise MCPConnectionError(f"Failed to start MCP server: {e}") from e

    async def disconnect(self) -> None:
        """Stop the MCP server subprocess."""
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
        self._connected = False
        logger.info("Disconnected from MCP server")

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server using JSON-RPC."""
        request = MCPRequest(
            id=str(self._request_id),
            method="tools/call",
            params={"name": tool_name, "arguments": arguments}
        )
        self._request_id += 1
        response = await self._send_request(request)

        if response.error:
            raise MCPRequestError(f"MCP tool call error: {response.error}")

        return response.result or {}

    async def call_method(self, method: str, params: dict[str, Any] | None = None) -> MCPResponse:
        """Call a generic MCP method."""
        request = MCPRequest(id=str(self._request_id), method=method, params=params)
        self._request_id += 1
        return await self._send_request(request)

    async def _send_request(self, request: MCPRequest) -> MCPResponse:
        """Send a JSON-RPC request and receive response."""
        if not self._connected or not self._process:
            raise MCPConnectionError("Not connected to MCP server")

        request_json = json.dumps(request.__dict__) + "\n"
        try:
            self._process.stdin.write(request_json.encode())
            self._process.stdin.flush()
        except BrokenPipeError as e:
            raise MCPConnectionError(f"MCP server stdin closed: {e}") from e

        # Read response line
        try:
            response_line = self._process.stdout.readline()
            if not response_line:
                raise MCPConnectionError("MCP server closed stdout")
            response_data = json.loads(response_line)
            return MCPResponse(**response_data)
        except json.JSONDecodeError as e:
            raise MCPRequestError(f"Invalid JSON from MCP server: {e}") from e
        except Exception as e:
            raise MCPConnectionError(f"Failed to read MCP response: {e}") from e

    @property
    def is_connected(self) -> bool:
        """Check if connected to MCP server."""
        return self._connected and self._process is not None and self._process.poll() is None


class HTTPMCPClient:
    """MCP client that communicates over HTTP.

    Parameters
    ----------
    base_url : str
        Base URL of the MCP HTTP server.
    """

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._connected = False

    async def connect(self) -> bool:
        """Check if the HTTP MCP server is reachable."""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self._base_url}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    self._connected = resp.status == 200
                    if self._connected:
                        logger.info("Connected to MCP HTTP server: %s", self._base_url)
                    return self._connected
        except Exception as e:
            logger.warning("MCP HTTP server health check failed: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close connections (no-op for HTTP client)."""
        self._connected = False

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server using HTTP."""
        import aiohttp
        if not self._connected:
            raise MCPConnectionError("Not connected to MCP server")

        request = MCPRequest(
            id="1",
            method="tools/call",
            params={"name": tool_name, "arguments": arguments}
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/rpc",
                    json=request.__dict__,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        raise MCPRequestError(f"MCP HTTP returned status {resp.status}")
                    data = await resp.json()
                    if "error" in data:
                        raise MCPRequestError(f"MCP tool call error: {data['error']}")
                    return data.get("result", {})
        except aiohttp.ClientError as e:
            raise MCPConnectionError(f"MCP HTTP request failed: {e}") from e

    async def call_method(self, method: str, params: dict[str, Any] | None = None) -> MCPResponse:
        """Call a generic MCP method over HTTP."""
        import aiohttp
        if not self._connected:
            raise MCPConnectionError("Not connected to MCP server")

        request = MCPRequest(id="1", method=method, params=params)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._base_url}/rpc",
                    json=request.__dict__,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    data = await resp.json()
                    return MCPResponse(**data)
        except aiohttp.ClientError as e:
            raise MCPConnectionError(f"MCP HTTP request failed: {e}") from e

    @property
    def is_connected(self) -> bool:
        """Check if connected to MCP server."""
        return self._connected


class MCPAdapter:
    """Main MCP adapter that manages MCP client connections.

    The adapter can use either stdio or HTTP transport depending on configuration.

    Parameters
    ----------
    transport : str
        Either "stdio" or "http".
    command : list[str], optional
        Command for stdio transport (required if transport="stdio").
    url : str, optional
        URL for HTTP transport (required if transport="http").
    """

    def __init__(
        self,
        transport: str = "stdio",
        command: list[str] | None = None,
        url: str | None = None,
    ) -> None:
        if transport not in ("stdio", "http"):
            raise ValueError(f"Invalid transport: {transport}")

        self._transport = transport
        self._client: MCPClientProtocol

        if transport == "stdio":
            if not command:
                raise ValueError("command required for stdio transport")
            self._client = StdioMCPClient(command)
        else:
            if not url:
                raise ValueError("url required for http transport")
            self._client = HTTPMCPClient(url)

    async def connect(self) -> bool:
        """Connect to the MCP server."""
        return await self._client.connect()

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        await self._client.disconnect()

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server."""
        return await self._client.call_tool(tool_name, arguments)

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools on the MCP server."""
        response = await self._client.call_method("tools/list")
        if response.error:
            raise MCPRequestError(f"Failed to list tools: {response.error}")
        return response.result or []

    @property
    def is_connected(self) -> bool:
        """Check if connected to MCP server."""
        return self._client.is_connected

    @property
    def transport(self) -> str:
        """Get the transport type."""
        return self._transport