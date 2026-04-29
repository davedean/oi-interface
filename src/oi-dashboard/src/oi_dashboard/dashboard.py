"""Dashboard server — aiohttp web app with SSE for real-time gateway updates."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import aiohttp
from aiohttp import web

logger = logging.getLogger(__name__)

# Default ports
DEFAULT_HOST = "localhost"
DEFAULT_API_PORT = 8788
DEFAULT_DASHBOARD_PORT = 8789


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
        from pathlib import Path
        static_dir = Path(__file__).parent.parent.parent / "static"
        self._app.router.add_get("/", self._index)
        self._app.router.add_get("/events", self._events_sse)
        self._app.router.add_get("/api/devices", self._api_devices)
        self._app.router.add_get("/api/devices/{device_id}", self._api_device_info)
        self._app.router.add_get("/api/transcripts", self._api_transcripts)
        self._app.router.add_get("/api/health", self._api_health)
        if static_dir.exists():
            self._app.router.add_static("/static", str(static_dir))

    async def _index(self, request: web.Request) -> web.Response:
        """Serve the dashboard HTML page."""
        from pathlib import Path
        html_path = Path(__file__).parent.parent.parent / "static" / "index.html"
        try:
            with open(html_path, "r") as f:
                html = f.read()
        except FileNotFoundError:
            html = self._get_inline_html()
        return web.Response(text=html, content_type="text/html")

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
            await response.write(f"event: {event_type}\ndata: {payload}\n\n".encode())
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
            "transcripts": self._transcripts[-50:],  # Last 50
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

    # ------------------------------------------------------------------
    # State Management
    # ------------------------------------------------------------------

    def _get_state_snapshot(self) -> dict[str, Any]:
        """Get current state for initial SSE connection."""
        return {
            "devices": {
                dev_id: {
                    "device_id": dev.device_id,
                    "device_type": dev.device_type,
                    "session_id": dev.session_id,
                    "online": dev.online,
                    "connected_at": dev.connected_at,
                    "last_seen": dev.last_seen,
                    "state": dev.state,
                    "capabilities": dev.capabilities,
                    "muted_until": dev.muted_until,
                    "audio_cache_bytes": dev.audio_cache_bytes,
                }
                for dev_id, dev in self._devices.items()
            },
            "transcripts": self._transcripts[-20:],
            "timestamp": datetime.now(timezone.utc).isoformat(),
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

    def _mark_device_offline(self, device_id: str) -> None:
        """Mark a device as offline."""
        if device_id in self._devices:
            self._devices[device_id].online = False

    def _add_transcript(self, device_id: str, transcript: str, response: str = "", stream_id: str = "") -> None:
        """Add a transcript entry."""
        entry = TranscriptEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
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
                # Get device list
                async with session.get(
                    f"{self._api_base}/api/devices",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        devices = data.get("devices", [])
                        changed = False
                        for dev_info in devices:
                            dev_id = dev_info.get("device_id", "")
                            if dev_id:
                                old_online = self._devices.get(dev_id, DeviceState()).online
                                self._update_device_state(dev_id, dev_info)
                                if not old_online and dev_info.get("online"):
                                    changed = True
                                    self._broadcast("device_online", dev_info)
                                elif old_online and not dev_info.get("online"):
                                    changed = True
                                    self._broadcast("device_offline", {"device_id": dev_id})

                        # Mark devices not in response as offline
                        current_ids = {d.get("device_id") for d in devices}
                        for dev_id in list(self._devices.keys()):
                            if dev_id and dev_id not in current_ids:
                                if self._devices[dev_id].online:
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
            self._broadcast("transcript", {
                "device_id": device_id,
                "transcript": transcript,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    def on_agent_response(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle agent response event."""
        # Update the most recent transcript with the response
        transcript = payload.get("transcript", "")
        response = payload.get("response_text", "")
        stream_id = payload.get("stream_id", "")
        if transcript and self._transcripts:
            for entry in reversed(self._transcripts):
                if entry.device_id == device_id and entry.transcript == transcript:
                    entry.response = response
                    break
        self._broadcast("agent_response", {
            "device_id": device_id,
            "transcript": transcript,
            "response": response,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def on_audio_delivered(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle audio delivered event."""
        if device_id in self._devices:
            # Update audio cache state if reported
            pass
        self._broadcast("audio_delivered", {
            "device_id": device_id,
            "response_id": payload.get("response_id"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # ------------------------------------------------------------------
    # Inline HTML (fallback if static file not found)
    # ------------------------------------------------------------------

    def _get_inline_html(self) -> str:
        """Return inline HTML when static file is not available."""
        return """<!DOCTYPE html>
<html>
<head>
    <title>Oi Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: system-ui, sans-serif; margin: 0; padding: 20px; background: #1a1a2e; color: #eee; }
        h1 { color: #00d4ff; margin-bottom: 20px; }
        .container { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; max-width: 1400px; margin: 0 auto; }
        .card { background: #16213e; border-radius: 8px; padding: 16px; }
        .card h2 { color: #00d4ff; margin-top: 0; font-size: 1.1em; }
        .device { display: flex; align-items: center; padding: 12px; margin: 8px 0; background: #0f3460; border-radius: 6px; }
        .status-dot { width: 12px; height: 12px; border-radius: 50%; margin-right: 12px; }
        .online { background: #00ff88; }
        .offline { background: #ff4757; }
        .device-info { flex: 1; }
        .device-name { font-weight: bold; color: #fff; }
        .device-type { color: #888; font-size: 0.85em; }
        .state-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; margin-left: 8px; }
        .transcript { padding: 10px; margin: 6px 0; background: #0f3460; border-radius: 6px; }
        .transcript-time { color: #666; font-size: 0.75em; }
        .transcript-text { color: #fff; margin: 4px 0; }
        .response-text { color: #00d4ff; font-size: 0.9em; margin-top: 4px; }
        .empty { color: #666; font-style: italic; }
        .full-width { grid-column: 1 / -1; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        @media (max-width: 900px) { .container { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <h1>🖥️ Oi Dashboard</h1>
    <div class="container">
        <div class="card full-width">
            <h2>Gateway Status</h2>
            <div id="gateway-status">Connecting...</div>
        </div>
        <div class="card">
            <h2>📱 Connected Devices</h2>
            <div id="devices-list"><div class="empty">No devices connected</div></div>
        </div>
        <div class="card">
            <h2>🔊 Audio Cache State</h2>
            <div id="audio-cache"><div class="empty">No audio data</div></div>
        </div>
        <div class="card full-width">
            <h2>💬 Recent Transcripts & Responses</h2>
            <div id="transcripts-list"><div class="empty">No transcripts yet</div></div>
        </div>
    </div>
    <script>
        const es = new EventSource('/events');
        let state = { devices: {}, transcripts: [] };

        function formatTime(iso) {
            if (!iso) return '';
            return new Date(iso).toLocaleTimeString();
        }

        function formatBytes(bytes) {
            if (!bytes) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        }

        function renderDevices() {
            const container = document.getElementById('devices-list');
            const devices = Object.values(state.devices);
            if (devices.length === 0) {
                container.innerHTML = '<div class="empty">No devices connected</div>';
                return;
            }
            container.innerHTML = devices.map(d => `
                <div class="device">
                    <div class="status-dot ${d.online ? 'online' : 'offline'}"></div>
                    <div class="device-info">
                        <div class="device-name">${d.device_id || 'Unknown'}
                            <span class="state-badge" style="background: ${d.online ? '#00ff88' : '#ff4757'}20; color: ${d.online ? '#00ff88' : '#ff4757'}">
                                ${d.online ? 'online' : 'offline'}
                            </span>
                        </div>
                        <div class="device-type">${d.device_type || 'Unknown device'}</div>
                        ${d.state?.mode ? `<div style="color: #888; font-size: 0.85em; margin-top: 4px;">Mode: ${d.state.mode}</div>` : ''}
                    </div>
                </div>
            `).join('');
        }

        function renderAudioCache() {
            const container = document.getElementById('audio-cache');
            const devices = Object.values(state.devices);
            const withCache = devices.filter(d => d.audio_cache_bytes > 0);
            if (withCache.length === 0) {
                container.innerHTML = '<div class="empty">No audio cached</div>';
                return;
            }
            container.innerHTML = withCache.map(d => `
                <div style="padding: 8px 0; border-bottom: 1px solid #0f3460;">
                    <strong>${d.device_id}</strong>: ${formatBytes(d.audio_cache_bytes)}
                </div>
            `).join('');
        }

        function renderTranscripts() {
            const container = document.getElementById('transcripts-list');
            const transcripts = state.transcripts.slice(-10).reverse();
            if (transcripts.length === 0) {
                container.innerHTML = '<div class="empty">No transcripts yet</div>';
                return;
            }
            container.innerHTML = transcripts.map(t => `
                <div class="transcript">
                    <div class="transcript-time">${formatTime(t.timestamp)} — ${t.device_id}</div>
                    <div class="transcript-text">👤 ${t.transcript}</div>
                    ${t.response ? `<div class="response-text">🤖 ${t.response}</div>` : ''}
                </div>
            `).join('');
        }

        function updateGatewayStatus() {
            fetch('/api/health')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('gateway-status').innerHTML = `
                        <span style="color: #00ff88">●</span> Gateway OK — 
                        ${data.devices_online || 0} device(s) online
                    `;
                })
                .catch(() => {
                    document.getElementById('gateway-status').innerHTML = 
                        '<span style="color: #ff4757">●</span> Gateway unreachable';
                });
        }

        es.onmessage = (e) => {
            const msg = JSON.parse(e.data);
            if (msg.type === 'init') {
                state = msg.data;
                renderDevices();
                renderAudioCache();
                renderTranscripts();
            } else if (msg.type === 'device_online' || msg.type === 'device_offline') {
                const d = msg.data;
                if (d.device_id && state.devices[d.device_id]) {
                    state.devices[d.device_id].online = msg.type === 'device_online';
                }
                renderDevices();
            } else if (msg.type === 'transcript') {
                state.transcripts.push({
                    timestamp: msg.data.timestamp,
                    device_id: msg.data.device_id,
                    transcript: msg.data.transcript,
                    response: ''
                });
                renderTranscripts();
            } else if (msg.type === 'agent_response') {
                for (let i = state.transcripts.length - 1; i >= 0; i--) {
                    if (state.transcripts[i].transcript === msg.data.transcript) {
                        state.transcripts[i].response = msg.data.response;
                        break;
                    }
                }
                renderTranscripts();
            } else if (msg.type === 'state_updated') {
                if (state.devices[msg.data.device_id]) {
                    Object.assign(state.devices[msg.data.device_id].state, msg.data.state);
                }
                renderDevices();
            }
        };

        es.onerror = () => {
            document.getElementById('gateway-status').innerHTML = 
                '<span style="color: #ff4757">●</span> SSE disconnected (will reconnect)';
        };

        // Update gateway status periodically
        setInterval(updateGatewayStatus, 5000);
        updateGatewayStatus();
    </script>
</body>
</html>"""


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
