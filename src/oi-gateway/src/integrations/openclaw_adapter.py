"""OpenClaw agent adapter for oi-gateway.

OpenClaw is an agent system that communicates over HTTP JSON API.
This adapter allows oi-gateway to connect to and interact with OpenClaw agents.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class OpenClawRequest:
    """An OpenClaw request message."""
    action: str
    payload: dict[str, Any]
    request_id: str | None = None


@dataclass
class OpenClawResponse:
    """An OpenClaw response message."""
    status: str  # "success" or "error"
    data: Any = None
    error: str | None = None
    request_id: str | None = None


@runtime_checkable
class OpenClawConnectionProtocol(Protocol):
    """Protocol for OpenClaw connection implementations."""

    async def connect(self) -> bool:
        """Connect to the OpenClaw agent."""
        ...

    async def disconnect(self) -> None:
        """Disconnect from the OpenClaw agent."""
        ...

    async def send_message(self, action: str, payload: dict[str, Any]) -> OpenClawResponse:
        """Send a message to the OpenClaw agent."""
        ...

    async def receive_response(self, timeout: float = 30.0) -> OpenClawResponse | None:
        """Receive a response from the OpenClaw agent."""
        ...


class OpenClawAdapterError(Exception):
    """Error in OpenClaw adapter."""
    pass


class OpenClawConnectionError(OpenClawAdapterError):
    """Failed to connect to OpenClaw agent."""
    pass


class OpenClawRequestError(OpenClawAdapterError):
    """OpenClaw request failed."""
    pass


class OpenClawTimeoutError(OpenClawAdapterError):
    """OpenClaw request timed out."""
    pass


class HTTPOpenClawConnection:
    """OpenClaw connection that communicates over HTTP.

    Parameters
    ----------
    base_url : str
        Base URL of the OpenClaw agent API.
    api_key : str, optional
        API key for authentication.
    timeout : float
        Default timeout for requests in seconds.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None
        self._connected = False
        self._request_id = 0
        self._pending_responses: dict[str, asyncio.Future[OpenClawResponse]] = {}

    async def connect(self) -> bool:
        """Connect to the OpenClaw agent API."""
        try:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
            # Test connection with a health check
            async with self._session.get(
                f"{self._base_url}/health",
                headers=self._get_headers(),
            ) as resp:
                if resp.status == 200:
                    self._connected = True
                    logger.info("Connected to OpenClaw agent: %s", self._base_url)
                    return True
                elif resp.status == 404:
                    # Health endpoint might not exist, try root
                    async with self._session.get(
                        self._base_url,
                        headers=self._get_headers(),
                    ) as root_resp:
                        self._connected = root_resp.status < 400
                        return self._connected
                else:
                    self._connected = False
                    return False
        except aiohttp.ClientError as e:
            logger.warning("Failed to connect to OpenClaw agent: %s", e)
            self._connected = False
            return False
        except Exception as e:
            logger.error("Unexpected error connecting to OpenClaw: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from the OpenClaw agent."""
        if self._session:
            await self._session.close()
            self._session = None
        self._connected = False
        # Cancel any pending responses
        for future in self._pending_responses.values():
            if not future.done():
                future.set_result(OpenClawResponse(status="error", error="Connection closed"))
        self._pending_responses.clear()
        logger.info("Disconnected from OpenClaw agent")

    async def send_message(
        self,
        action: str,
        payload: dict[str, Any],
    ) -> OpenClawResponse:
        """Send a message to the OpenClaw agent."""
        if not self._connected or not self._session:
            raise OpenClawConnectionError("Not connected to OpenClaw agent")

        self._request_id += 1
        request_id = str(self._request_id)

        request = OpenClawRequest(
            action=action,
            payload=payload,
            request_id=request_id,
        )

        try:
            async with self._session.post(
                f"{self._base_url}/api/v1/execute",
                json={
                    "action": request.action,
                    "payload": request.payload,
                    "request_id": request.request_id,
                },
                headers=self._get_headers(),
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise OpenClawRequestError(
                        f"OpenClaw API returned status {resp.status}: {text}"
                    )

                data = await resp.json()
                return OpenClawResponse(
                    status=data.get("status", "success"),
                    data=data.get("data"),
                    error=data.get("error"),
                    request_id=data.get("request_id"),
                )
        except aiohttp.ClientError as e:
            raise OpenClawConnectionError(f"Failed to send message to OpenClaw: {e}") from e

    async def receive_response(self, timeout: float = 30.0) -> OpenClawResponse | None:
        """Receive a response from the OpenClaw agent (polling)."""
        if not self._connected or not self._session:
            raise OpenClawConnectionError("Not connected to OpenClaw agent")

        try:
            async with self._session.get(
                f"{self._base_url}/api/v1/responses",
                headers=self._get_headers(),
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return OpenClawResponse(
                        status=data.get("status", "success"),
                        data=data.get("data"),
                        error=data.get("error"),
                        request_id=data.get("request_id"),
                    )
                elif resp.status == 204:
                    return None  # No response waiting
                else:
                    return None
        except asyncio.TimeoutError:
            raise OpenClawTimeoutError("Timed out waiting for OpenClaw response") from None
        except aiohttp.ClientError as e:
            raise OpenClawConnectionError(f"Failed to receive response from OpenClaw: {e}") from e

    def _get_headers(self) -> dict[str, str]:
        """Get HTTP headers including optional API key."""
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    @property
    def is_connected(self) -> bool:
        """Check if connected to OpenClaw agent."""
        return self._connected

    @property
    def base_url(self) -> str:
        """Get the base URL."""
        return self._base_url


class OpenClawAdapter:
    """Main OpenClaw adapter that manages connection to OpenClaw agent.

    Parameters
    ----------
    base_url : str
        Base URL of the OpenClaw agent API.
    api_key : str, optional
        API key for authentication.
    timeout : float
        Default timeout for requests in seconds.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._connection = HTTPOpenClawConnection(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )

    async def connect(self) -> bool:
        """Connect to the OpenClaw agent."""
        return await self._connection.connect()

    async def disconnect(self) -> None:
        """Disconnect from the OpenClaw agent."""
        await self._connection.disconnect()

    async def send_message(
        self,
        action: str,
        payload: dict[str, Any],
    ) -> OpenClawResponse:
        """Send a message to the OpenClaw agent."""
        return await self._connection.send_message(action, payload)

    async def receive_response(self, timeout: float = 30.0) -> OpenClawResponse | None:
        """Receive a response from the OpenClaw agent."""
        return await self._connection.receive_response(timeout)

    async def execute_task(self, task: str, params: dict[str, Any]) -> OpenClawResponse:
        """Execute a task on the OpenClaw agent."""
        return await self.send_message("execute_task", {"task": task, "params": params})

    async def query_status(self) -> OpenClawResponse:
        """Query the status of the OpenClaw agent."""
        return await self.send_message("status", {})

    async def list_capabilities(self) -> list[str]:
        """List available capabilities of the OpenClaw agent."""
        response = await self.send_message("capabilities", {})
        if response.status == "success" and response.data:
            return response.data.get("capabilities", [])
        return []

    @property
    def is_connected(self) -> bool:
        """Check if connected to OpenClaw agent."""
        return self._connection.is_connected

    @property
    def base_url(self) -> str:
        """Get the base URL."""
        return self._connection.base_url