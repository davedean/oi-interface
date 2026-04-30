"""SSE transport adapter for dashboard fanout and connection lifecycle."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from aiohttp import web

logger = logging.getLogger(__name__)


class SseHub:
    """Own SSE client registration, fanout, and shutdown behavior."""

    def __init__(self) -> None:
        self.clients: set[web.StreamResponse] = set()

    async def connect(self, request: web.Request, init_data: Any) -> web.StreamResponse:
        """Prepare an SSE stream, register it, and send the initial payload."""
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)
        self.clients.add(response)
        await self.send_event(response, "init", init_data)
        return response

    async def keepalive(
        self,
        response: web.StreamResponse,
        *,
        is_running: Callable[[], bool],
        interval_seconds: float = 30,
    ) -> None:
        """Keep an SSE stream alive until shutdown or disconnect."""
        try:
            while is_running():
                await asyncio.sleep(interval_seconds)
                if response.prepared:
                    await response.write(b": ping\n\n")
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self.clients.discard(response)

    async def send_event(self, response: web.StreamResponse, event_type: str, data: Any) -> None:
        """Send a default SSE message event with a typed JSON payload."""
        if not response.prepared:
            return
        try:
            payload = json.dumps({"type": event_type, "data": data})
            await response.write(f"data: {payload}\n\n".encode())
        except Exception as error:
            logger.debug("SSE send failed: %s", error)

    def broadcast(self, event_type: str, data: Any) -> None:
        """Schedule an SSE event for every connected client."""
        for client in list(self.clients):
            asyncio.create_task(self.send_event(client, event_type, data))

    async def close(self) -> None:
        """Finish all connected SSE responses."""
        for client in list(self.clients):
            try:
                if client.prepared:
                    await client.write_eof()
            except Exception:
                pass
