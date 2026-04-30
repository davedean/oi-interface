"""OiSim — scriptable virtual DATP device."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import websockets

from sim.device_api import OiSimDeviceAPI
from sim.state import InvalidTransition, State, StateMachine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TraceEvent:
    """Structured trace entry for simulator activity."""

    ts: str
    direction: str
    kind: str
    data: dict[str, Any]

# ------------------------------------------------------------------
# Defaults
# ------------------------------------------------------------------

DEFAULT_CAPABILITIES: dict[str, Any] = {
    "input": ["hold_to_record", "double_tap", "tap", "button_confirm"],
    "output": ["tiny_screen", "cached_audio", "character"],
    "sensors": ["battery", "wifi_rssi"],
    "commands_supported": [
        "display.show_status",
        "display.show_card",
        "display.show_progress",
        "display.show_response_delta",
        "audio.cache.put_begin",
        "audio.cache.put_chunk",
        "audio.cache.put_end",
        "audio.play",
        "audio.stop",
        "device.set_brightness",
        "device.mute_until",
        "device.set_volume",
        "device.set_led",
        "device.reboot",
        "device.shutdown",
        "storage.format",
        "wifi.configure",
    ],
    "display_width": 24,
    "display_height": 6,
    "has_audio_input": True,
    "has_audio_output": True,
}


def _now_iso() -> str:
    """Current UTC timestamp in DATP format."""
    return (
        datetime.now(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    )


def _new_id(prefix: str = "msg") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _trace_event_payload(event: TraceEvent) -> dict[str, Any]:
    """Convert a trace event to the JSONL payload written to disk."""
    return {
        "ts": event.ts,
        "direction": event.direction,
        "kind": event.kind,
        "data": event.data,
    }


# ------------------------------------------------------------------
# OiSim
# ------------------------------------------------------------------

class OiSim(OiSimDeviceAPI):
    """Scriptable DATP WebSocket client that impersonates a physical device.

    Parameters
    ----------
    gateway : str
        WebSocket URL of the oi-gateway DATP endpoint.
        Default: ``ws://localhost:8787/datp``.
    device_id : str
        Identifier for this virtual device.
        Default: ``oi-sim-001``.
    device_type : str
        Human-readable device type (sent in hello).
        Default: ``oi-stick``.
    capabilities : dict | None
        Capability set to advertise in hello.
        Defaults to ``DEFAULT_CAPABILITIES``.
    """

    def __init__(
        self,
        gateway: str = "ws://localhost:8787/datp",
        device_id: str = "oi-sim-001",
        device_type: str = "oi-stick",
        capabilities: dict[str, Any] | None = None,
        *,
        strict: bool = False,
        trace_path: str | Path | None = None,
        reconnect_backoff_seconds: float = 0.1,
    ) -> None:
        self.gateway = gateway
        self.device_id = device_id
        self.device_type = device_type
        self.capabilities = capabilities or dict(DEFAULT_CAPABILITIES)
        self.strict = strict
        self.trace_path = Path(trace_path) if trace_path is not None else None
        self.reconnect_backoff_seconds = reconnect_backoff_seconds

        self._ws: websockets.WebSocketClientProtocol | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._state_machine = StateMachine(State.READY)
        self._session_id: str | None = None

        # Incoming message queues / snapshots
        self._received_commands: list[dict[str, Any]] = []
        self._received_messages: list[dict[str, Any]] = []
        self._pending_acks: dict[str, asyncio.Future[bool]] = {}
        self._connected = False
        self._trace: list[TraceEvent] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> State:
        """Current device state."""
        return self._state_machine.state

    @property
    def display_state(self) -> str | None:
        """Last display state from display.show_status command, or None."""
        return self._state_machine._display_state

    @property
    def display_label(self) -> str | None:
        """Last display label from display.show_status command, or None."""
        return self._state_machine._display_label

    @property
    def muted_until(self) -> str | None:
        """Timestamp from device.mute_until command, or None."""
        return self._state_machine._muted_until

    @property
    def volume(self) -> int:
        """Current volume level (0-100)."""
        return self._state_machine.volume

    @property
    def led_enabled(self) -> bool:
        """Whether LED is enabled."""
        return self._state_machine.led_enabled

    @property
    def brightness(self) -> int:
        """Current brightness level (0-100)."""
        return self._state_machine.brightness

    @property
    def received_commands(self) -> list[dict[str, Any]]:
        """All command payloads received from the gateway."""
        return list(self._received_commands)

    @property
    def received_messages(self) -> list[dict[str, Any]]:
        """All messages received from the gateway (including commands, acks, errors)."""
        return list(self._received_messages)

    @property
    def is_connected(self) -> bool:
        """Whether the simulator currently considers itself connected."""
        return self._connected

    @property
    def trace_events(self) -> list[TraceEvent]:
        """Structured trace events captured for this simulator session."""
        return list(self._trace)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect to the gateway, send hello, wait for hello_ack, start listening."""
        if self._connected:
            raise RuntimeError("Already connected")

        self._ws = await websockets.connect(self.gateway)
        self._connected = True
        await self._ws.send(json.dumps(self._build_hello_message()))

        raw = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
        self._session_id = self._parse_hello_ack(raw)
        self._listen_task = asyncio.create_task(self._listen_loop())

    async def disconnect(self) -> None:
        """Close the WebSocket connection cleanly."""
        if not self._connected:
            return

        self._connected = False
        self._record_trace("lifecycle", "disconnect_begin", {"device_id": self.device_id})

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        self._record_trace("lifecycle", "disconnect_complete", {"device_id": self.device_id})

    async def reconnect(self) -> None:
        """Disconnect, reset local session state, wait briefly, then reconnect."""
        await self.disconnect()
        self._reset_for_reconnect()
        self._state_machine = StateMachine(State.READY)
        self._record_trace(
            "lifecycle",
            "reconnect_wait",
            {"device_id": self.device_id, "backoff_seconds": self.reconnect_backoff_seconds},
        )
        await asyncio.sleep(self.reconnect_backoff_seconds)
        await self.connect()

    # ------------------------------------------------------------------
    # Internal listener
    # ------------------------------------------------------------------

    async def _process_message(self, msg: dict[str, Any]) -> None:
        """Process a single received DATP message.

        This is the shared logic for both live WebSocket reception and
        fixture injection. It records the message, advances the state
        machine, and sends acknowledgements.
        """
        self._received_messages.append(msg)
        self._record_trace("recv", msg.get("type", "unknown"), msg)

        msg_type = msg.get("type", "")
        payload = msg.get("payload", {})

        if msg_type == "command":
            await self._handle_command_message(msg, payload)
        elif msg_type == "error":
            self._handle_error_message(payload)
        elif msg_type == "ack":
            self._resolve_pending_ack(payload)

    async def _handle_command_message(self, msg: dict[str, Any], payload: dict[str, Any]) -> None:
        """Apply an incoming command and acknowledge it when connected."""
        op = payload.get("op", "")
        args = payload.get("args", {})
        try:
            self._state_machine.receive_command(op, args)
        except InvalidTransition as exc:
            if self.strict:
                raise
            logger.debug("Ignoring invalid transition for command %r: %s", op, exc)

        self._received_commands.append(payload)
        if self._ws is not None:
            await self._send_ack(msg.get("id", ""))

    def _handle_error_message(self, payload: dict[str, Any]) -> None:
        """Record a gateway error by attempting to move into ERROR state."""
        code = payload.get("code", "")
        logger.warning("Gateway error: %s — %s", code, payload.get("message", ""))
        try:
            self._state_machine.transition(State.ERROR)
        except InvalidTransition:
            pass

    def _resolve_pending_ack(self, payload: dict[str, Any]) -> None:
        """Resolve any local future waiting on a gateway acknowledgement."""
        cmd_id = payload.get("command_id", "")
        future = self._pending_acks.pop(cmd_id, None)
        if future and not future.done():
            future.set_result(payload.get("ok", True))

    async def _listen_loop(self) -> None:
        """Background task: receive messages, record commands, send acks."""
        assert self._ws is not None
        try:
            async for raw in self._ws:
                msg: dict[str, Any] = json.loads(raw)
                await self._process_message(msg)

        except websockets.ConnectionClosed:
            self._connected = False
            self._record_trace("lifecycle", "connection_closed", {"device_id": self.device_id})
        except asyncio.CancelledError:
            raise
        except Exception:
            if self._connected:
                self._connected = False
                logger.exception("Unexpected error in listen loop")

    # ------------------------------------------------------------------
    # Outbound helpers
    # ------------------------------------------------------------------

    async def _send(self, msg_type: str, payload: dict[str, Any]) -> None:
        """Send a DATP message of the given type."""
        assert self._ws is not None, "Not connected"
        msg = self._build_message(msg_type, payload)
        await self._ws.send(json.dumps(msg))
        self._record_trace("send", msg_type, msg)

    async def _send_event(self, event: str, **payload: Any) -> None:
        """Send a DATP event message."""
        await self._send("event", {"event": event, **payload})

    async def _send_ack(self, command_id: str, ok: bool = True) -> None:
        """Acknowledge a command received from the gateway."""
        await self._send("ack", {"command_id": command_id, "ok": ok})

    def _reset_for_reconnect(self) -> None:
        """Reset reconnect-sensitive local state before a fresh hello/session."""
        self._session_id = None
        self._pending_acks.clear()
        self._received_commands.clear()
        self._received_messages.clear()

    def _build_hello_message(self) -> dict[str, Any]:
        """Build the initial DATP hello handshake payload."""
        return self._build_message(
            "hello",
            {
                "device_type": self.device_type,
                "protocol": "datp",
                "firmware": f"oi-sim/{self.device_type}",
                "capabilities": self.capabilities,
                "state": {
                    "mode": "READY",
                    "battery_percent": 100,
                    "wifi_rssi": -50,
                },
                "nonce": secrets.token_hex(8),
            },
            message_id=_new_id("hello"),
        )

    def _parse_hello_ack(self, raw: str) -> str | None:
        """Parse the hello acknowledgement and return the session id."""
        resp: dict[str, Any] = json.loads(raw)
        if resp.get("type") != "hello_ack":
            raise RuntimeError(f"Expected hello_ack, got {resp.get('type')!r}")
        return resp.get("payload", {}).get("session_id")

    def _build_message(
        self,
        msg_type: str,
        payload: dict[str, Any],
        *,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        """Build a DATP envelope for an outbound message."""
        return {
            "v": "datp",
            "type": msg_type,
            "id": message_id or _new_id(msg_type[:4]),
            "device_id": self.device_id,
            "ts": _now_iso(),
            "payload": payload,
        }

    def _record_trace(self, direction: str, kind: str, data: dict[str, Any]) -> None:
        """Record a structured trace event and optionally append it to JSONL."""
        event = TraceEvent(ts=_now_iso(), direction=direction, kind=kind, data=data)
        self._trace.append(event)
        self._write_trace_event(event)

    def _write_trace_event(self, event: TraceEvent) -> None:
        """Append a trace event to the optional JSONL trace file."""
        if self.trace_path is None:
            return

        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_trace_event_payload(event)) + "\n")
