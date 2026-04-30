"""Gateway HTTP adapter for dashboard polling and proxy routes."""
from __future__ import annotations

from typing import Any

import aiohttp


class GatewayApi:
    """Fetch gateway projections over HTTP behind a small adapter seam."""

    def __init__(
        self,
        api_base_url: str,
        timeout_seconds: float = 5,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._api_base = api_base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session = session
        self._owns_session = session is None

    async def get_devices(self) -> tuple[int, dict[str, Any]]:
        """Return the gateway device projection."""
        return await self._get_json("/api/devices")

    async def get_device_info(self, device_id: str) -> tuple[int, dict[str, Any]]:
        """Return a single device projection."""
        return await self._get_json(f"/api/devices/{device_id}")

    async def get_health(self) -> tuple[int, dict[str, Any]]:
        """Return the gateway health projection."""
        return await self._get_json("/api/health")

    async def close(self) -> None:
        """Close the owned HTTP session, if any."""
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()

    async def _get_json(self, path: str) -> tuple[int, dict[str, Any]]:
        """Fetch and decode a gateway JSON resource."""
        session = self._session
        if session is None:
            session = aiohttp.ClientSession()
            self._session = session
            self._owns_session = True
        async with session.get(f"{self._api_base}{path}", timeout=self._timeout) as response:
            return response.status, await response.json()
