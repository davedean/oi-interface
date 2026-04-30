"""Dashboard server — aiohttp web app with SSE for real-time gateway updates."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

from .fallback_html import INLINE_DASHBOARD_HTML

logger = logging.getLogger(__name__)

# Default ports
DEFAULT_HOST = "localhost"
DEFAULT_API_PORT = 8788
DEFAULT_DASHBOARD_PORT = 8789
STATIC_DIR = Path(__file__).parent.parent.parent / "static"


@dataclass
class DeviceState:
    """Current state for a single device."""
    device_id: str = ""
    device_type: str = ""
    session_id: str = ""
    online: bool = False
    connected_at: str | None = None
    last_seen: str | None = None
    state: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    muted_until: str | None = None
    audio_cache_bytes: int = 0


@dataclass
class TranscriptEntry:
    """A transcript/response pair."""
    timestamp: str
    device_id: str
    transcript: str
    response: str = ""
    stream_id: str = ""


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
    ) -> None:
        self._api_base = api_base_url.rstrip("/")
        self._host = host
        self._port = port
        self._poll_interval = poll_interval
        self._max_transcripts = max_transcripts

        # State
        self._devices: dict[str, DeviceState] = {}
        self._transcripts: list[TranscriptEntry] = []
        self._sse_clients: set[web.StreamResponse] = set()
        self._running = False
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._poll_task: asyncio.Task | None = None

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
        # Read back the actual bound port (may differ if port=0 was passed for OS assignment)
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
        # Close all SSE connections
        for client in list(self._sse_clients):
            try:
                await client.close()
            except Exception:
                pass
        if self._runner:
            await self._runner.cleanup()
        logger.info("Dashboard stopped")

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    def _setup_routes(self) -> None:
        """Register HTTP routes."""
        self._app.router.add_get("/", self._index)
        self._app.router.add_get("/events", self._events_sse)
        self._app.router.add_get("/api/devices", self._api_devices)
        self._app.router.add_get("/api/devices/{device_id}", self._api_device_info)
        self._app.router.add_get("/api/transcripts", self._api_transcripts)
        self._app.router.add_get("/api/health", self._api_health)
        if STATIC_DIR.exists():
            self._app.router.add_static("/static", str(STATIC_DIR))

    async def _index(self, request: web.Request) -> web.Response:
        """Serve the dashboard HTML page."""
        return web.Response(text=self._load_index_html(), content_type="text/html")

    async def _events_sse(self, request: web.Request) -> web.StreamResponse:
        """Server-Sent Events endpoint for real-time updates."""
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
        self._sse_clients.add(response)

        # Send initial state
        await self._send_sse_event(response, "init", self._get_state_snapshot())

        try:
            # Keep connection alive with periodic pings
            while self._running:
                await asyncio.sleep(30)
                if response.prepared:
                    await response.write(b": ping\n\n")
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self._sse_clients.discard(response)

        return response

    async def _send_sse_event(self, response: web.StreamResponse, event_type: str, data: Any) -> None:
        """Send an SSE event to a client."""
        if not response.prepared:
            return
        try:
            payload = json.dumps({"type": event_type, "data": data})
            await response.write(f"data: {payload}\n\n".encode())
        except Exception as e:
            logger.debug("SSE send failed: %s", e)

    def _broadcast(self, event_type: str, data: Any) -> None:
        """Broadcast an SSE event to all connected clients."""
        for client in list(self._sse_clients):
            asyncio.create_task(self._send_sse_event(client, event_type, data))

    async def _api_devices(self, request: web.Request) -> web.Response:
        """Proxy to gateway /api/devices."""
        return await self._proxy_request(f"{self._api_base}/api/devices")

    async def _api_device_info(self, request: web.Request) -> web.Response:
        """Proxy to gateway /api/devices/{id}."""
        device_id = request.match_info["device_id"]
        return await self._proxy_request(f"{self._api_base}/api/devices/{device_id}")

    async def _api_transcripts(self, request: web.Request) -> web.Response:
        """Return cached transcript entries."""
        return self._json_response({
            "transcripts": self._transcript_payloads(self._transcripts[-50:]),  # Last 50
            "count": len(self._transcripts),
        })

    async def _api_health(self, request: web.Request) -> web.Response:
        """Proxy to gateway /api/health."""
        return await self._proxy_request(f"{self._api_base}/api/health")

    async def _proxy_request(self, url: str) -> web.Response:
        """Proxy an HTTP GET request to the gateway."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    body = await resp.json()
                    return self._json_response(body, status=resp.status)
        except aiohttp.ClientError as e:
            logger.warning("Gateway proxy failed for %s: %s", url, e)
            return self._json_response({"error": str(e)}, status=502)

    def _json_response(self, data: Any, status: int = 200) -> web.Response:
        return web.Response(
            text=json.dumps(data, indent=2),
            content_type="application/json",
            status=status,
        )

    def _load_index_html(self) -> str:
        """Return the static dashboard page or the inline fallback."""
        html_path = STATIC_DIR / "index.html"
        try:
            return html_path.read_text()
        except FileNotFoundError:
            return INLINE_DASHBOARD_HTML

    def _timestamped_device_event(self, device_id: str, **payload: Any) -> dict[str, Any]:
        """Build a device event payload with a server timestamp."""
        return {
            "device_id": device_id,
            **payload,
            "timestamp": self._utc_now_iso(),
        }

    # ------------------------------------------------------------------
    # State Management
    # ------------------------------------------------------------------

    def _get_state_snapshot(self) -> dict[str, Any]:
        """Get current state for initial SSE connection."""
        return {
            "devices": {
                dev_id: self._device_payload(dev)
                for dev_id, dev in self._devices.items()
            },
            "transcripts": self._transcript_payloads(self._transcripts[-20:]),
            "timestamp": self._utc_now_iso(),
        }

    def _update_device_state(self, device_id: str, info: dict[str, Any]) -> None:
        """Update or create a device entry."""
        dev = self._devices.get(device_id, DeviceState(device_id=device_id))
        dev.device_id = info.get("device_id", device_id)
        dev.device_type = info.get("device_type", "")
        dev.session_id = info.get("session_id", "")
        dev.online = info.get("online", True)
        dev.connected_at = info.get("connected_at")
        dev.last_seen = info.get("last_seen")
        dev.state = info.get("state", {})
        dev.capabilities = info.get("capabilities", {})
        dev.muted_until = info.get("muted_until")
        dev.audio_cache_bytes = info.get("audio_cache_bytes", 0)
        self._devices[device_id] = dev

    def _device_payload(self, device: DeviceState) -> dict[str, Any]:
        """Serialize a device state for HTTP/SSE payloads."""
        return {
            "device_id": device.device_id,
            "device_type": device.device_type,
            "session_id": device.session_id,
            "online": device.online,
            "connected_at": device.connected_at,
            "last_seen": device.last_seen,
            "state": device.state,
            "capabilities": device.capabilities,
            "muted_until": device.muted_until,
            "audio_cache_bytes": device.audio_cache_bytes,
        }

    def _transcript_payload(self, entry: TranscriptEntry) -> dict[str, str]:
        """Serialize a transcript entry for HTTP/SSE payloads."""
        return {
            "timestamp": entry.timestamp,
            "device_id": entry.device_id,
            "transcript": entry.transcript,
            "response": entry.response,
            "stream_id": entry.stream_id,
        }

    def _transcript_payloads(self, entries: list[TranscriptEntry]) -> list[dict[str, str]]:
        """Serialize a list of transcript entries."""
        return [self._transcript_payload(entry) for entry in entries]

    def _utc_now_iso(self) -> str:
        """Return the current UTC time as an ISO-8601 string."""
        return datetime.now(timezone.utc).isoformat()

    def _mark_device_offline(self, device_id: str) -> None:
        """Mark a device as offline."""
        if device_id in self._devices:
            self._devices[device_id].online = False

    def _sync_polled_device(self, device_id: str, info: dict[str, Any]) -> None:
        """Merge a polled device payload and emit online/offline transitions."""
        was_online = self._devices.get(device_id, DeviceState()).online
        is_online = info.get("online", True)
        self._update_device_state(device_id, info)
        if not was_online and is_online:
            self._broadcast("device_online", info)
        elif was_online and not is_online:
            self._broadcast("device_offline", {"device_id": device_id})

    def _add_transcript(self, device_id: str, transcript: str, response: str = "", stream_id: str = "") -> None:
        """Add a transcript entry."""
        entry = TranscriptEntry(
            timestamp=self._utc_now_iso(),
            device_id=device_id,
            transcript=transcript,
            response=response,
            stream_id=stream_id,
        )
        self._transcripts.append(entry)
        # Trim to max size
        if len(self._transcripts) > self._max_transcripts:
            self._transcripts = self._transcripts[-self._max_transcripts:]

    # ------------------------------------------------------------------
    # Polling Loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Poll gateway API and update local state."""
        await asyncio.sleep(1)  # Initial delay
        while self._running:
            try:
                await self._poll_gateway_state()
            except Exception as e:
                logger.warning("Poll loop error: %s", e)
            await asyncio.sleep(self._poll_interval)

    async def _poll_gateway_state(self) -> None:
        """Poll gateway API for current state."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._api_base}/api/devices",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status != 200:
                        return

                    data = await resp.json()
                    devices = data.get("devices", [])
                    current_ids = set()
                    for dev_info in devices:
                        dev_id = dev_info.get("device_id", "")
                        if not dev_id:
                            continue
                        current_ids.add(dev_id)
                        self._sync_polled_device(dev_id, dev_info)

                    for dev_id in list(self._devices):
                        if dev_id and dev_id not in current_ids and self._devices[dev_id].online:
                            self._devices[dev_id].online = False
                            self._broadcast("device_offline", {"device_id": dev_id})

        except aiohttp.ClientError as e:
            logger.debug("Poll failed (gateway may be down): %s", e)

    # ------------------------------------------------------------------
    # Event Handlers (called by gateway integration)
    # ------------------------------------------------------------------

    def on_device_online(self, device_id: str, info: dict[str, Any]) -> None:
        """Handle device online event."""
        self._update_device_state(device_id, {**info, "online": True})
        self._broadcast("device_online", {"device_id": device_id, **info})

    def on_device_offline(self, device_id: str) -> None:
        """Handle device offline event."""
        self._mark_device_offline(device_id)
        self._broadcast("device_offline", {"device_id": device_id})

    def on_state_updated(self, device_id: str, state: dict[str, Any]) -> None:
        """Handle device state update event."""
        if device_id in self._devices:
            self._devices[device_id].state.update(state)
        self._broadcast("state_updated", {"device_id": device_id, "state": state})

    def on_transcript(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle transcript event."""
        transcript = payload.get("cleaned", "") or payload.get("text", "")
        if transcript:
            self._add_transcript(device_id, transcript)
            self._broadcast(
                "transcript",
                self._timestamped_device_event(device_id, transcript=transcript),
            )

    def on_agent_response(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle agent response event."""
        transcript = payload.get("transcript", "")
        response = payload.get("response_text", "")
        if transcript and self._transcripts:
            for entry in reversed(self._transcripts):
                if entry.device_id == device_id and entry.transcript == transcript:
                    entry.response = response
                    break
        self._broadcast(
            "agent_response",
            self._timestamped_device_event(
                device_id,
                transcript=transcript,
                response=response,
            ),
        )

    def on_audio_delivered(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle audio delivered event."""
        self._broadcast(
            "audio_delivered",
            self._timestamped_device_event(
                device_id,
                response_id=payload.get("response_id"),
            ),
        )

# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_dashboard: Dashboard | None = None


def get_dashboard(
    api_base_url: str | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_DASHBOARD_PORT,
) -> Dashboard:
    """Get or create the dashboard singleton."""
    global _dashboard
    if _dashboard is None:
        _dashboard = Dashboard(
            api_base_url=api_base_url or f"http://{DEFAULT_HOST}:{DEFAULT_API_PORT}",
            host=host,
            port=port,
        )
    return _dashboard


async def run_dashboard(
    api_base_url: str | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_DASHBOARD_PORT,
) -> None:
    """Run the dashboard server (blocking)."""
    dashboard = get_dashboard(api_base_url, host, port)
    await dashboard.start()
    try:
        await asyncio.Event().wait()  # Run forever
    except KeyboardInterrupt:
        pass
    finally:
        await dashboard.stop()
