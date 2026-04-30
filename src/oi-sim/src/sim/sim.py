"""OiSim — scriptable virtual DATP device."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import websockets

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


# ------------------------------------------------------------------
# OiSim
# ------------------------------------------------------------------

class OiSim:
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

        # Send hello with proper handshake spec structure
        hello_id = _new_id("hello")
        hello = {
            "v": "datp",
            "type": "hello",
            "id": hello_id,
            "device_id": self.device_id,
            "ts": _now_iso(),
            "payload": {
                "device_type": self.device_type,
                "protocol": "datp",
                "firmware": f"oi-sim/{self.device_type}",
                "capabilities": self.capabilities,
                "state": {
                    "mode": "READY",
                    "battery_percent": 100,  # simulated
                    "wifi_rssi": -50,        # simulated
                },
                "nonce": secrets.token_hex(8),
            },
        }
        await self._ws.send(json.dumps(hello))

        # Wait for hello_ack
        raw = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
        resp: dict[str, Any] = json.loads(raw)

        if resp.get("type") != "hello_ack":
            raise RuntimeError(f"Expected hello_ack, got {resp.get('type')!r}")

        self._session_id = resp.get("payload", {}).get("session_id")

        # Start background listener
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
        msg = {
            "v": "datp",
            "type": msg_type,
            "id": _new_id(msg_type[:4]),
            "device_id": self.device_id,
            "ts": _now_iso(),
            "payload": payload,
        }
        await self._ws.send(json.dumps(msg))
        self._record_trace("send", msg_type, msg)

    async def _send_event(self, event: str, **payload: Any) -> None:
        """Send a DATP event message."""
        await self._send("event", {"event": event, **payload})

    async def _send_ack(self, command_id: str, ok: bool = True) -> None:
        """Acknowledge a command received from the gateway."""
        await self._send("ack", {"command_id": command_id, "ok": ok})

    # ------------------------------------------------------------------
    # Button / event API
    # ------------------------------------------------------------------

    async def press_long_hold(self) -> None:
        """Send button.long_hold_started → transitions READY → RECORDING."""
        self._state_machine.transition(State.RECORDING)
        await self._send("event", {
            "event": "button.long_hold_started",
            "button": "main",
        })

    async def release(self) -> None:
        """Send audio.recording_finished → transitions RECORDING → UPLOADING."""
        self._state_machine.transition(State.UPLOADING)
        await self._send("event", {
            "event": "audio.recording_finished",
            "stream_id": _new_id("rec"),
            "duration_ms": 1000,
        })

    async def tap(self) -> None:
        """Send button.tap event (stop playback when playing)."""
        await self._send("event", {"event": "button.tap", "button": "main"})

    async def press_button(self) -> None:
        """Send button.pressed event for a short button press."""
        await self._send("event", {"event": "button.pressed", "button": "main"})

    async def press_very_long_hold(self) -> None:
        """Send button.very_long_hold_started (>3s) → transitions to MUTED.

        This is used for the "Mute for 30 min" action from the button grammar.
        """
        self._state_machine.transition(State.MUTED)
        await self._send("event", {
            "event": "button.very_long_hold_started",
            "button": "main",
            "duration_ms": 3000,
        })

    async def double_tap(self) -> None:
        """Send button.double_tap → transitions RESPONSE_CACHED → PLAYING."""
        self._state_machine.transition(State.PLAYING)
        await self._send("event", {"event": "button.double_tap", "button": "main"})

    # ------------------------------------------------------------------
    # Text input events
    # ------------------------------------------------------------------

    async def send_text_prompt(self, text: str) -> None:
        """Send a text prompt to the agent.

        This is for devices with text input capability (keyboard, touchscreen).
        The gateway will route this to the agent and return a text response.

        Parameters
        ----------
        text : str
            The text prompt to send to the agent.
        """
        # New prompts should move into THINKING, but this call is idempotent if
        # we're already waiting on a response.
        if self._state_machine.state != State.THINKING:
            self._state_machine.transition(State.THINKING)
        await self._send_event("text.prompt", text=text)

    # ------------------------------------------------------------------
    # Playback events
    # ------------------------------------------------------------------

    async def send_playback_started(self, response_id: str | None = None) -> None:
        """Send audio.playback_started event.

        Parameters
        ----------
        response_id : str, optional
            The response ID being played. Defaults to "latest".
        """
        await self._send_event("audio.playback_started", response_id=response_id or "latest")

    async def send_playback_finished(self, response_id: str | None = None) -> None:
        """Send audio.playback_finished event → transitions PLAYING → RESPONSE_CACHED.

        Parameters
        ----------
        response_id : str, optional
            The response ID that finished playing. Defaults to "latest".
        """
        # Only transition if currently PLAYING
        if self._state_machine.state == State.PLAYING:
            self._state_machine.transition(State.RESPONSE_CACHED)
        await self._send_event("audio.playback_finished", response_id=response_id or "latest")

    # ------------------------------------------------------------------
    # Battery and power events
    # ------------------------------------------------------------------

    async def send_battery_low(self) -> None:
        """Send battery_low event when battery is below threshold."""
        await self._send_event("battery_low", battery_percent=10)

    async def send_charging_started(self) -> None:
        """Send charging_started event when charging begins."""
        await self._send_event("charging_started", battery_percent=15)

    async def send_charging_stopped(self) -> None:
        """Send charging_stopped event when charging ends."""
        await self._send_event("charging_stopped", battery_percent=100)

    # ------------------------------------------------------------------
    # WiFi events
    # ------------------------------------------------------------------

    async def send_wifi_connected(self, ssid: str = "MyNetwork") -> None:
        """Send wifi.connected event when WiFi connects."""
        await self._send_event("wifi.connected", ssid=ssid, rssi=-50)

    async def send_wifi_disconnected(self) -> None:
        """Send wifi.disconnected event when WiFi disconnects."""
        await self._send_event("wifi.disconnected")

    # ------------------------------------------------------------------
    # Error events
    # ------------------------------------------------------------------

    async def send_device_error(self, code: str, message: str) -> None:
        """Send a device.error event.

        Parameters
        ----------
        code : str
            Error code (e.g., 'AUDIO_BUFFER_FULL', 'WIFI_FAILED')
        message : str
            Human-readable error message.
        """
        await self._send_event("device.error", code=code, message=message)

    # ------------------------------------------------------------------
    # Sensor events
    # ------------------------------------------------------------------

    async def send_battery_update(self, percent: int, charging: bool = False) -> None:
        """Send periodic battery status update.

        Parameters
        ----------
        percent : int
            Battery percentage (0-100).
        charging : bool
            Whether the device is charging.
        """
        await self._send_event("sensor.battery_update", battery_percent=percent, charging=charging)

    async def send_wifi_update(self, rssi: int, ssid: str | None = None) -> None:
        """Send periodic WiFi status update.

        Parameters
        ----------
        rssi : int
            WiFi signal strength in dBm.
        ssid : str, optional
            The connected SSID.
        """
        payload: dict[str, Any] = {"rssi": rssi}
        if ssid:
            payload["ssid"] = ssid
        await self._send_event("sensor.wifi_update", **payload)

    # ------------------------------------------------------------------
    # Storage events
    # ------------------------------------------------------------------

    async def send_storage_low(self, bytes_free: int) -> None:
        """Send storage_low event when storage is running low.

        Parameters
        ----------
        bytes_free : int
            Number of free bytes remaining.
        """
        await self._send_event("storage.low", bytes_free=bytes_free)

    async def send_storage_full(self) -> None:
        """Send storage_full event when storage is completely full."""
        await self._send_event("storage.full")

    async def send_storage_available(self, bytes_free: int) -> None:
        """Send storage_available event after cleanup or format.

        Parameters
        ----------
        bytes_free : int
            Number of free bytes now available.
        """
        await self._send_event("storage.available", bytes_free=bytes_free)

    # ------------------------------------------------------------------
    # Network events
    # ------------------------------------------------------------------

    async def send_network_online(self) -> None:
        """Send network.online event when network becomes available."""
        await self._send_event("network.online")

    async def send_network_offline(self) -> None:
        """Send network.offline event when network becomes unavailable."""
        await self._send_event("network.offline")

    # ------------------------------------------------------------------
    # Display events
    # ------------------------------------------------------------------

    async def send_display_touched(self, x: int, y: int) -> None:
        """Send display.touched event when screen is touched.

        Parameters
        ----------
        x : int
            X coordinate of touch.
        y : int
            Y coordinate of touch.
        """
        await self._send_event("display.touched", x=x, y=y)

    async def send_display_released(self) -> None:
        """Send display.released event when screen touch is released."""
        await self._send_event("display.released")

    # ------------------------------------------------------------------
    # Button timeout event
    # ------------------------------------------------------------------

    async def send_button_timeout(self, button: str = "main") -> None:
        """Send button.timeout event when button is held too long without release.

        Parameters
        ----------
        button : str
            The button that timed out. Default: "main".
        """
        await self._send_event("button.timeout", button=button)

    # ------------------------------------------------------------------
    # Capability update events
    # ------------------------------------------------------------------

    async def send_capability_updated(
        self,
        added: list[str] | None = None,
        removed: list[str] | None = None,
    ) -> None:
        """Send device.capability_updated event when device capabilities change.

        Parameters
        ----------
        added : list[str], optional
            List of newly added capabilities.
        removed : list[str], optional
            List of removed capabilities.
        """
        payload: dict[str, Any] = {}
        if added:
            payload["added"] = added
        if removed:
            payload["removed"] = removed
        await self._send_event("device.capability_updated", **payload)

    # ------------------------------------------------------------------
    # Audio upload
    # ------------------------------------------------------------------

    async def upload_audio_file(self, path: str) -> str:
        """Read a WAV file, stream it as audio_chunk messages, then emit recording_finished.

        Parameters
        ----------
        path : str
            Path to the audio file to upload.

        Returns
        -------
        str
            The ``stream_id`` assigned to this upload.
        """
        stream_id = _new_id("rec")

        # Read raw bytes; for simplicity we accept any binary file and chunk it.
        with open(path, "rb") as fh:
            data = fh.read()

        # Split into small base64 chunks (simulate real PCM streaming).
        chunk_size = 512  # bytes of raw audio per chunk
        num_chunks = 0
        for seq, start in enumerate(range(0, len(data), chunk_size)):
            chunk = data[start : start + chunk_size]
            await self._send("audio_chunk", {
                "stream_id": stream_id,
                "seq": seq,
                "format": "pcm16",
                "sample_rate": 16000,
                "channels": 1,
                "data_b64": base64.b64encode(chunk).decode(),
            })
            num_chunks += 1

        # Emit recording_finished to signal end of stream.
        # Duration is estimated: num_chunks * chunk_size / sample_rate / 2 (16-bit = 2 bytes per sample)
        duration_ms = int((num_chunks * chunk_size / 16000 / 2) * 1000)
        await self._send("event", {
            "event": "audio.recording_finished",
            "stream_id": stream_id,
            "duration_ms": duration_ms,
        })

        return stream_id

    async def upload_audio_text(self, text: str) -> str:
        """Convert text to a simple audio chunk sequence.

        In a real device this would be PCM from the microphone.
        Here we generate a short synthetic chunk as a placeholder.
        """
        stream_id = _new_id("rec")
        # Placeholder: a minimal silent audio chunk
        placeholder = base64.b64encode(b"\x00" * 1024).decode()
        await self._send("audio_chunk", {
            "stream_id": stream_id,
            "seq": 0,
            "format": "pcm16",
            "sample_rate": 16000,
            "channels": 1,
            "data_b64": placeholder,
        })
        return stream_id

    # ------------------------------------------------------------------
    # State reporting
    # ------------------------------------------------------------------

    async def send_state_report(self, state: str | State | None = None) -> None:
        """Send a DATP state report message.

        Parameters
        ----------
        state : str | State | None
            The semantic state to report. Defaults to the current state machine value.
        """
        if state is None:
            state = self._state_machine.state
        if isinstance(state, State):
            state = state.value

        await self._send("state", {
            "mode": state,
            "battery_percent": 95,
            "charging": False,
            "wifi_rssi": -55,
            "heap_free": 200000,
            "uptime_s": 0,
            "audio_cache_used_bytes": 0,
            "muted_until": None,
        })

    # ------------------------------------------------------------------
    # Assertions (for tests)
    # ------------------------------------------------------------------

    def assert_state(self, expected: State) -> None:
        """Assert the state machine is in ``expected`` state."""
        self._state_machine.assert_state(expected)

    def assert_command_received(self, op: str) -> None:
        """Assert a command with operator ``op`` was received from the gateway."""
        assert any(
            cmd.get("op") == op for cmd in self._received_commands
        ), f"Command {op!r} was not received. Got: {self._received_commands}"

    def assert_command_not_received(self, op: str) -> None:
        """Assert no command with operator ``op`` was received."""
        assert not any(
            cmd.get("op") == op for cmd in self._received_commands
        ), f"Command {op!r} should not have been received"

    def assert_log_contains(self, text: str) -> None:
        """Assert the device's received messages contain ``text`` (JSON-serialised)."""
        serialised = json.dumps(self._received_messages)
        assert text in serialised, (
            f"Log does not contain {text!r}. "
            f"Received: {serialised[:500]}"
        )

    def assert_trace_contains(self, kind: str, direction: str | None = None) -> None:
        """Assert a structured trace event with ``kind`` exists."""
        assert any(
            event.kind == kind and (direction is None or event.direction == direction)
            for event in self._trace
        ), f"Trace missing kind={kind!r} direction={direction!r}: {self._trace}"

    # ------------------------------------------------------------------
    # Error simulation
    # ------------------------------------------------------------------

    async def simulate_network_error(self, message: str = "Network unavailable") -> None:
        """Simulate a network-related error.

        Parameters
        ----------
        message : str
            Error message description.
        """
        await self.send_device_error("NETWORK_ERROR", message)

    async def simulate_storage_error(self, message: str = "Storage operation failed") -> None:
        """Simulate a storage-related error.

        Parameters
        ----------
        message : str
            Error message description.
        """
        await self.send_device_error("STORAGE_ERROR", message)

    def _reset_for_reconnect(self) -> None:
        """Reset reconnect-sensitive local state before a fresh hello/session."""
        self._session_id = None
        self._pending_acks.clear()
        self._received_commands.clear()
        self._received_messages.clear()

    def _record_trace(self, direction: str, kind: str, data: dict[str, Any]) -> None:
        """Record a structured trace event and optionally append it to JSONL."""
        event = TraceEvent(ts=_now_iso(), direction=direction, kind=kind, data=data)
        self._trace.append(event)
        if self.trace_path is not None:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self.trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "ts": event.ts,
                    "direction": event.direction,
                    "kind": event.kind,
                    "data": event.data,
                }) + "\n")

    async def simulate_audio_error(self, message: str = "Audio playback failed") -> None:
        """Simulate an audio-related error.

        Parameters
        ----------
        message : str
            Error message description.
        """
        await self.send_device_error("AUDIO_ERROR", message)

    async def simulate_wifi_error(self, message: str = "WiFi connection failed") -> None:
        """Simulate a WiFi-related error.

        Parameters
        ----------
        message : str
            Error message description.
        """
        await self.send_device_error("WIFI_ERROR", message)

    async def simulate_timeout_error(self, message: str = "Operation timed out") -> None:
        """Simulate a timeout error.

        Parameters
        ----------
        message : str
            Error message description.
        """
        await self.send_device_error("TIMEOUT", message)

    async def simulate_invalid_state(self, message: str = "Invalid state for operation") -> None:
        """Simulate an invalid state error (device enters ERROR state).

        Parameters
        ----------
        message : str
            Error message description.
        """
        self._state_machine.transition(State.ERROR)
        await self.send_device_error("INVALID_STATE", message)

    async def simulate_critical_error(self, code: str, message: str) -> None:
        """Simulate a critical error that puts device into ERROR state.

        Parameters
        ----------
        code : str
            Error code (e.g., 'CRITICAL_BATTERY', 'HARDWARE_FAILURE')
        message : str
            Human-readable error message.
        """
        self._state_machine.transition(State.ERROR)
        await self.send_device_error(code, message)
