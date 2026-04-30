"""Public device-facing API methods mixed into ``OiSim``."""
from __future__ import annotations

import base64
import json
import uuid
from typing import TYPE_CHECKING, Any

from sim.state import State

if TYPE_CHECKING:
    from sim.sim import OiSim


AUDIO_CHUNK_SIZE_BYTES = 512
PLACEHOLDER_AUDIO_MIN_BYTES = 1024


def _new_stream_id() -> str:
    return f"rec_{uuid.uuid4().hex[:12]}"


def _placeholder_audio_bytes(text: str) -> bytes:
    """Return silent placeholder PCM sized from the source text length."""
    sample_count = max(PLACEHOLDER_AUDIO_MIN_BYTES, len(text.encode("utf-8")) * 32)
    return b"\x00" * sample_count


class OiSimDeviceAPI:
    """Outbound event helpers, test assertions, and error simulation for ``OiSim``."""

    async def press_long_hold(self: OiSim) -> None:
        """Send button.long_hold_started → transitions READY → RECORDING."""
        self._state_machine.transition(State.RECORDING)
        await self._send("event", {
            "event": "button.long_hold_started",
            "button": "main",
        })

    async def release(self: OiSim) -> None:
        """Send audio.recording_finished → transitions RECORDING → UPLOADING."""
        self._state_machine.transition(State.UPLOADING)
        await self._send("event", {
            "event": "audio.recording_finished",
            "stream_id": _new_stream_id(),
            "duration_ms": 1000,
        })

    async def tap(self: OiSim) -> None:
        """Send button.tap event (stop playback when playing)."""
        await self._send("event", {"event": "button.tap", "button": "main"})

    async def press_button(self: OiSim) -> None:
        """Send button.pressed event for a short button press."""
        await self._send("event", {"event": "button.pressed", "button": "main"})

    async def press_very_long_hold(self: OiSim) -> None:
        """Send button.very_long_hold_started (>3s) → transitions to MUTED."""
        self._state_machine.transition(State.MUTED)
        await self._send("event", {
            "event": "button.very_long_hold_started",
            "button": "main",
            "duration_ms": 3000,
        })

    async def double_tap(self: OiSim) -> None:
        """Send button.double_tap → transitions RESPONSE_CACHED → PLAYING."""
        self._state_machine.transition(State.PLAYING)
        await self._send("event", {"event": "button.double_tap", "button": "main"})

    async def send_text_prompt(self: OiSim, text: str) -> None:
        """Send a text prompt to the agent."""
        if self._state_machine.state != State.THINKING:
            self._state_machine.transition(State.THINKING)
        await self._send_event("text.prompt", text=text)

    async def send_playback_started(self: OiSim, response_id: str | None = None) -> None:
        """Send audio.playback_started event."""
        await self._send_event("audio.playback_started", response_id=response_id or "latest")

    async def send_playback_finished(self: OiSim, response_id: str | None = None) -> None:
        """Send audio.playback_finished event → transitions PLAYING → RESPONSE_CACHED."""
        if self._state_machine.state == State.PLAYING:
            self._state_machine.transition(State.RESPONSE_CACHED)
        await self._send_event("audio.playback_finished", response_id=response_id or "latest")

    async def send_battery_low(self: OiSim) -> None:
        """Send battery_low event when battery is below threshold."""
        await self._send_event("battery_low", battery_percent=10)

    async def send_charging_started(self: OiSim) -> None:
        """Send charging_started event when charging begins."""
        await self._send_event("charging_started", battery_percent=15)

    async def send_charging_stopped(self: OiSim) -> None:
        """Send charging_stopped event when charging ends."""
        await self._send_event("charging_stopped", battery_percent=100)

    async def send_wifi_connected(self: OiSim, ssid: str = "MyNetwork") -> None:
        """Send wifi.connected event when WiFi connects."""
        await self._send_event("wifi.connected", ssid=ssid, rssi=-50)

    async def send_wifi_disconnected(self: OiSim) -> None:
        """Send wifi.disconnected event when WiFi disconnects."""
        await self._send_event("wifi.disconnected")

    async def send_device_error(self: OiSim, code: str, message: str) -> None:
        """Send a device.error event."""
        await self._send_event("device.error", code=code, message=message)

    async def send_battery_update(self: OiSim, percent: int, charging: bool = False) -> None:
        """Send periodic battery status update."""
        await self._send_event("sensor.battery_update", battery_percent=percent, charging=charging)

    async def send_wifi_update(self: OiSim, rssi: int, ssid: str | None = None) -> None:
        """Send periodic WiFi status update."""
        payload: dict[str, Any] = {"rssi": rssi}
        if ssid:
            payload["ssid"] = ssid
        await self._send_event("sensor.wifi_update", **payload)

    async def send_storage_low(self: OiSim, bytes_free: int) -> None:
        """Send storage.low event when storage is running low."""
        await self._send_event("storage.low", bytes_free=bytes_free)

    async def send_storage_full(self: OiSim) -> None:
        """Send storage.full event when storage is completely full."""
        await self._send_event("storage.full")

    async def send_storage_available(self: OiSim, bytes_free: int) -> None:
        """Send storage.available event after cleanup or format."""
        await self._send_event("storage.available", bytes_free=bytes_free)

    async def send_network_online(self: OiSim) -> None:
        """Send network.online event when network becomes available."""
        await self._send_event("network.online")

    async def send_network_offline(self: OiSim) -> None:
        """Send network.offline event when network becomes unavailable."""
        await self._send_event("network.offline")

    async def send_display_touched(self: OiSim, x: int, y: int) -> None:
        """Send display.touched event when screen is touched."""
        await self._send_event("display.touched", x=x, y=y)

    async def send_display_released(self: OiSim) -> None:
        """Send display.released event when screen touch is released."""
        await self._send_event("display.released")

    async def send_button_timeout(self: OiSim, button: str = "main") -> None:
        """Send button.timeout event when button is held too long without release."""
        await self._send_event("button.timeout", button=button)

    async def send_capability_updated(
        self: OiSim,
        added: list[str] | None = None,
        removed: list[str] | None = None,
    ) -> None:
        """Send device.capability_updated event when device capabilities change."""
        payload: dict[str, Any] = {}
        if added:
            payload["added"] = added
        if removed:
            payload["removed"] = removed
        await self._send_event("device.capability_updated", **payload)

    async def upload_audio_file(self: OiSim, path: str) -> str:
        """Read a file, stream it as audio_chunk messages, then emit recording_finished."""
        stream_id = _new_stream_id()
        with open(path, "rb") as handle:
            data = handle.read()

        num_chunks = 0
        for seq, start in enumerate(range(0, len(data), AUDIO_CHUNK_SIZE_BYTES)):
            chunk = data[start : start + AUDIO_CHUNK_SIZE_BYTES]
            await self._send("audio_chunk", {
                "stream_id": stream_id,
                "seq": seq,
                "format": "pcm16",
                "sample_rate": 16000,
                "channels": 1,
                "data_b64": base64.b64encode(chunk).decode(),
            })
            num_chunks += 1

        duration_ms = int((num_chunks * AUDIO_CHUNK_SIZE_BYTES / 16000 / 2) * 1000)
        await self._send("event", {
            "event": "audio.recording_finished",
            "stream_id": stream_id,
            "duration_ms": duration_ms,
        })
        return stream_id

    async def upload_audio_text(self: OiSim, text: str) -> str:
        """Upload placeholder silent PCM sized from the source text length."""
        stream_id = _new_stream_id()
        placeholder = base64.b64encode(_placeholder_audio_bytes(text)).decode()
        await self._send("audio_chunk", {
            "stream_id": stream_id,
            "seq": 0,
            "format": "pcm16",
            "sample_rate": 16000,
            "channels": 1,
            "data_b64": placeholder,
        })
        return stream_id

    async def send_state_report(self: OiSim, state: str | State | None = None) -> None:
        """Send a DATP state report message."""
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

    def assert_state(self: OiSim, expected: State) -> None:
        """Assert the state machine is in ``expected`` state."""
        self._state_machine.assert_state(expected)

    def assert_command_received(self: OiSim, op: str) -> None:
        """Assert a command with operator ``op`` was received from the gateway."""
        assert any(cmd.get("op") == op for cmd in self._received_commands), (
            f"Command {op!r} was not received. Got: {self._received_commands}"
        )

    def assert_command_not_received(self: OiSim, op: str) -> None:
        """Assert no command with operator ``op`` was received."""
        assert not any(cmd.get("op") == op for cmd in self._received_commands), (
            f"Command {op!r} should not have been received"
        )

    def assert_log_contains(self: OiSim, text: str) -> None:
        """Assert the device's received messages contain ``text`` (JSON-serialised)."""
        serialised = json.dumps(self._received_messages)
        assert text in serialised, (
            f"Log does not contain {text!r}. Received: {serialised[:500]}"
        )

    def assert_trace_contains(self: OiSim, kind: str, direction: str | None = None) -> None:
        """Assert a structured trace event with ``kind`` exists."""
        assert any(
            event.kind == kind and (direction is None or event.direction == direction)
            for event in self._trace
        ), f"Trace missing kind={kind!r} direction={direction!r}: {self._trace}"

    async def simulate_network_error(self: OiSim, message: str = "Network unavailable") -> None:
        """Simulate a network-related error."""
        await self._simulate_error("NETWORK_ERROR", message)

    async def simulate_storage_error(self: OiSim, message: str = "Storage operation failed") -> None:
        """Simulate a storage-related error."""
        await self._simulate_error("STORAGE_ERROR", message)

    async def simulate_audio_error(self: OiSim, message: str = "Audio playback failed") -> None:
        """Simulate an audio-related error."""
        await self._simulate_error("AUDIO_ERROR", message)

    async def simulate_wifi_error(self: OiSim, message: str = "WiFi connection failed") -> None:
        """Simulate a WiFi-related error."""
        await self._simulate_error("WIFI_ERROR", message)

    async def simulate_timeout_error(self: OiSim, message: str = "Operation timed out") -> None:
        """Simulate a timeout error."""
        await self._simulate_error("TIMEOUT", message)

    async def simulate_invalid_state(self: OiSim, message: str = "Invalid state for operation") -> None:
        """Simulate an invalid-state error and move the device into ERROR."""
        await self._simulate_error("INVALID_STATE", message, transition_to_error=True)

    async def simulate_critical_error(self: OiSim, code: str, message: str) -> None:
        """Simulate a critical error and move the device into ERROR."""
        await self._simulate_error(code, message, transition_to_error=True)

    async def _simulate_error(
        self: OiSim,
        code: str,
        message: str,
        *,
        transition_to_error: bool = False,
    ) -> None:
        """Send a device error, optionally transitioning the state machine first."""
        if transition_to_error:
            self._state_machine.transition(State.ERROR)
        await self.send_device_error(code, message)
