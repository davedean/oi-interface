"""Dashboard server — aiohttp web app with SSE for real-time gateway updates."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp
from aiohttp import web

from .browser_app import DASHBOARD_APP_JS
from .browser_shell import DASHBOARD_SHELL_CSS, dashboard_shell_html
from .event_payloads import normalize_agent_response_payload, normalize_transcript_payload
from .gateway_api import GatewayApi
from .poller import DashboardPoller
from .sse import SseHub
from .state import DashboardState

logger = logging.getLogger(__name__)

# Default ports
DEFAULT_HOST = "localhost"
DEFAULT_API_PORT = 8788
DEFAULT_DASHBOARD_PORT = 8789


class Dashboard:
    """Real-time web dashboard for oi-gateway.

    Provides:
    - SSE endpoint at /events for real-time updates
    - REST polling of oi-gateway API at /api/*
    - Static file serving for the web UI

    Parameters
    ----------
    api_base_url : str
        Base URL of oi-gateway API (e.g., "http://localhost:8788").
    host : str
        Dashboard HTTP bind address.
    port : int
        Dashboard HTTP port.
    poll_interval : float
        Seconds between polling the gateway API (default 2.0).
    max_transcripts : int
        Max transcript entries to keep in memory (default 100).
    """

    def __init__(
        self,
        api_base_url: str = f"http://{DEFAULT_HOST}:{DEFAULT_API_PORT}",
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_DASHBOARD_PORT,
        poll_interval: float = 2.0,
        max_transcripts: int = 100,
        state: DashboardState | None = None,
        gateway_api: GatewayApi | None = None,
        sse_hub: SseHub | None = None,
    ) -> None:
        self._api_base = api_base_url.rstrip("/")
        self._host = host
        self._port = port
        self._poll_interval = poll_interval
        self._state = state or DashboardState(max_transcripts=max_transcripts)
        self._gateway_api = gateway_api or GatewayApi(api_base_url)
        self._sse_hub = sse_hub or SseHub()
        self._poller = DashboardPoller(self._gateway_api, self._state)
        self._running = False
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._poll_task: asyncio.Task | None = None

    @property
    def state(self) -> DashboardState:
        """Expose the dashboard projection through its dedicated module seam."""
        return self._state

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the dashboard HTTP server and polling loop."""
        self._app = web.Application()
        self._setup_routes()
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        for sock in site._server.sockets or []:
            self._port = sock.getsockname()[1]
            break
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Dashboard listening at http://%s:%d", self._host, self._port)

    async def stop(self) -> None:
        """Stop the dashboard server and polling loop."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        await self._sse_hub.close()
        await self._gateway_api.close()
        if self._runner:
            await self._runner.cleanup()
        logger.info("Dashboard stopped")

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    def _setup_routes(self) -> None:
        """Register HTTP routes."""
        assert self._app is not None
        self._app.router.add_get("/", self._index)
        self._app.router.add_get("/events", self._events_sse)
        self._app.router.add_get("/dashboard-app.js", self._dashboard_app_js)
        self._app.router.add_get("/dashboard-shell.css", self._dashboard_shell_css)
        self._app.router.add_get("/api/devices", self._api_devices)
        self._app.router.add_get("/api/devices/{device_id}", self._api_device_info)
        self._app.router.add_get("/api/transcripts", self._api_transcripts)
        self._app.router.add_get("/api/health", self._api_health)

    async def _index(self, _request: web.Request) -> web.Response:
        """Serve the dashboard HTML page."""
        return web.Response(text=self._load_index_html(), content_type="text/html")

    async def _events_sse(self, request: web.Request) -> web.StreamResponse:
        """Server-Sent Events endpoint for real-time updates."""
        response = await self._sse_hub.connect(request, self._state.snapshot())
        await self._sse_hub.keepalive(response, is_running=lambda: self._running)
        return response

    async def _dashboard_app_js(self, _request: web.Request) -> web.Response:
        """Serve the shared browser-side dashboard application logic."""
        return web.Response(text=DASHBOARD_APP_JS, content_type="application/javascript")

    async def _dashboard_shell_css(self, _request: web.Request) -> web.Response:
        """Serve the shared dashboard shell styling."""
        return web.Response(text=DASHBOARD_SHELL_CSS, content_type="text/css")

    async def _send_sse_event(self, response: web.StreamResponse, event_type: str, data: Any) -> None:
        """Send an SSE event to a client."""
        await self._sse_hub.send_event(response, event_type, data)

    def _broadcast(self, event_type: str, data: Any) -> None:
        """Broadcast an SSE event to all connected clients."""
        self._sse_hub.broadcast(event_type, data)

    async def _api_devices(self, _request: web.Request) -> web.Response:
        """Proxy to gateway /api/devices."""
        return await self._gateway_proxy_response(self._gateway_api.get_devices)

    async def _api_device_info(self, request: web.Request) -> web.Response:
        """Proxy to gateway /api/devices/{id}."""
        return await self._gateway_proxy_response(
            self._gateway_api.get_device_info,
            request.match_info["device_id"],
        )

    async def _api_transcripts(self, _request: web.Request) -> web.Response:
        """Return cached transcript entries."""
        return self._json_response(self._state.transcript_listing())

    async def _api_health(self, _request: web.Request) -> web.Response:
        """Proxy to gateway /api/health."""
        return await self._gateway_proxy_response(self._gateway_api.get_health)

    async def _gateway_proxy_response(self, request_method, *args: Any) -> web.Response:
        """Call a gateway adapter method and translate failures into HTTP responses."""
        try:
            status, body = await request_method(*args)
            return self._json_response(body, status=status)
        except aiohttp.ClientError as error:
            logger.warning("Gateway proxy failed: %s", error)
            return self._json_response({"error": str(error)}, status=502)

    def _json_response(self, data: Any, status: int = 200) -> web.Response:
        return web.Response(
            text=json.dumps(data, indent=2),
            content_type="application/json",
            status=status,
        )

    def _load_index_html(self) -> str:
        """Return the canonical dashboard HTML shell."""
        return dashboard_shell_html()

    # ------------------------------------------------------------------
    # Polling Loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Poll gateway API and update local state."""
        await asyncio.sleep(1)
        while self._running:
            try:
                await self._poll_gateway_state()
            except Exception as error:
                logger.warning("Poll loop error: %s", error)
            await asyncio.sleep(self._poll_interval)

    async def _poll_gateway_state(self) -> None:
        """Poll gateway API for current state."""
        try:
            for event_type, payload in await self._poller.poll_once():
                self._broadcast(event_type, payload)

        except aiohttp.ClientError as error:
            logger.debug("Poll failed (gateway may be down): %s", error)

    # ------------------------------------------------------------------
    # Event Handlers (called by gateway integration)
    # ------------------------------------------------------------------

    def on_device_online(self, device_id: str, info: dict[str, Any]) -> None:
        """Handle device online event."""
        self._broadcast("device_online", self._state.record_device_online(device_id, info))

    def on_device_offline(self, device_id: str) -> None:
        """Handle device offline event."""
        self._broadcast("device_offline", self._state.record_device_offline(device_id))

    def on_state_updated(self, device_id: str, state: dict[str, Any]) -> None:
        """Handle device state update event."""
        self._broadcast("state_updated", self._state.record_state_updated(device_id, state))

    def on_transcript(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle transcript event."""
        event_payload = self._state.record_transcript(device_id, normalize_transcript_payload(payload))
        if event_payload is not None:
            self._broadcast("transcript", event_payload)

    def on_agent_response(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle agent response event."""
        self._broadcast(
            "agent_response",
            self._state.record_agent_response(device_id, normalize_agent_response_payload(payload)),
        )

    def on_audio_delivered(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle audio delivered event."""
        self._broadcast("audio_delivered", self._state.record_audio_delivered(device_id, payload))


def get_dashboard(
    api_base_url: str | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_DASHBOARD_PORT,
) -> Dashboard:
    """Build a dashboard instance with the default runtime wiring."""
    return Dashboard(
        api_base_url=api_base_url or f"http://{DEFAULT_HOST}:{DEFAULT_API_PORT}",
        host=host,
        port=port,
    )


async def run_dashboard(
    api_base_url: str | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_DASHBOARD_PORT,
) -> None:
    """Run the dashboard server (blocking)."""
    dashboard = get_dashboard(api_base_url, host, port)
    await dashboard.start()
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        await dashboard.stop()
