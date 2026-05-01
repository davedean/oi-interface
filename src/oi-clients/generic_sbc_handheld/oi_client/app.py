#!/usr/bin/env python3
"""Main Oi handheld app loop.

Ties together SDL2 input, renderer, audio, and DATP client.
"""

from __future__ import annotations

import asyncio
import glob
import os
import tempfile
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from enum import Enum
import uuid
from typing import Callable

from oi_client.state import State
from oi_client.input import Sdl2Input, InputEvent
from oi_client.button_mapping import check_manual_mapping_shortcut, run_button_mapping_wizard
from oi_client.renderer import Sdl2Renderer
from oi_client.audio import HandheldAudio
from oi_client.capabilities import build_capabilities
from oi_client.datp import DatpClient
from oi_client.delight import (
    SURPRISE_LABEL,
    SecretTracker,
    format_gateway_about,
    pick_celebration,
    pick_connecting_quip,
    pick_surprise_prompt,
    pick_waiting_quip,
)
from oi_client.device_control import DeviceController
from oi_client.telemetry import TelemetryCollector
import time


class UIMode(Enum):
    HOME = "home"
    CONNECTING = "connecting"
    READY = "ready"
    WAITING = "waiting"
    CARD = "card"
    MENU = "menu"
    ERROR = "error"
    OFFLINE = "offline"
    RECORDING = "recording"


# MVP canned prompts
CANNED_PROMPTS = [
    "What time is it?",
    "Status check",
    "Weather today",
    "Mute for 30 minutes",
    SURPRISE_LABEL,
]


@dataclass
class CardData:
    title: str = ""
    body: str = ""


logger = logging.getLogger(__name__)

_ASCII_STATES = (
    "idle",
    "listening",
    "uploading",
    "thinking",
    "response_cached",
    "playing",
    "confirm",
    "muted",
    "offline",
    "error",
    "safe_mode",
    "task_running",
    "blocked",
)

_ASCII_FRAMES_BIG: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "idle": (
        (" .---.", "( o o )", "(  -  )", " `-+-'"),
        (" .---.", "( ^ ^ )", "(  -  )", " `-+-'"),
    ),
    "listening": (
        (" .---.", "( o o ) )))", "(  -\\ )", " `-+-'"),
        (" .---.", "( O o ) ))))", "(  o\\ )", " `-+-'"),
    ),
    "uploading": (
        ("   ^", "   |", " .---.", "( o o )", "(  v/ )", " `-+-'"),
        ("   ^ ^", "   | |", " .---.", "( ^ o )", "(  v/ )", " `-+-'"),
    ),
    "thinking": (
        (" .---.", "( o o )", "(  ?  )", " `-+-'"),
        ("... .---.", "   ( - o )", "   (  ?  )", "    `-+-'"),
    ),
    "response_cached": (
        ("[db]✓", " .---.", "( o o )", "(  v  )", " `-+-'"),
        ("[db]✦", " .---.", "( ^ o )", "( \\v/ )", " `-+-'"),
    ),
    "playing": (
        ("  ♪", " .---.", "( o o )", "(  v/ )", " `-+-'"),
        ("  ♫", " .---.", "( ^ ^ )", "( \\v/ )", " `-+-'"),
    ),
    "confirm": (
        ("  ✓", " .---.", "( ^ o )", "(  v/ )", " `-+-'"),
        ("  ✓✓", " .---.", "( ^ ^ )", "( \\v/ )", " `-+-'"),
    ),
    "muted": (
        (" .---.  x", "( o o )", "(  sh )", " `-+-'"),
        (" .---.  x", "( - - )", "(  sh )", " `-+-'"),
    ),
    "offline": (
        (" .---.  _", "( - - )", "(  .  )", " `-+-'"),
        (" .---.  z", "( x - )", "(  .  )", " `-+-'"),
    ),
    "error": (
        ("  !", " .---.", "( o O )", "(  !  )", " `-+-'"),
        ("  !!!", " .---.", "( X X )", "(  ^  )", " `-+-'"),
    ),
    "safe_mode": (
        (" [#]", " .---.", "( o o )", "(  -  )", " `-+-'"),
        (" [###]", " .---.", "( > < )", "(  -  )", " `-+-'"),
    ),
    "task_running": (
        (" .---.  /", "( o o )", "(  [_] )", " `-+-'"),
        (" .---.  -", "( > o )", "(  [_] )", " `-+-'"),
    ),
    "blocked": (
        (" NO", " .---.", "( o o )", "(  |/ )", " `-+-'"),
        (" STOP", " .---.", "( > < )", "( \\|/ )", " `-+-'"),
    ),
}

_ASCII_FRAMES_SMALL: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "idle": (("(o_o)",), ("(^_^)",)),
    "listening": (("(o_o)))",), ("(O_o))))",)),
    "uploading": (("(o_o)^",), ("(^o^)^^",)),
    "thinking": (("(o_o)?",), ("(-o)...",)),
    "response_cached": (("(o_o)✓",), ("(^o^)✓",)),
    "playing": (("(o_o)♪",), ("(^_^)♫",)),
    "confirm": (("(^o)✓",), ("(^_^)✓",)),
    "muted": (("(o_o)x",), ("(-_-)x",)),
    "offline": (("(-_-)",), ("(x_-)",)),
    "error": (("(o_O)!",), ("(X_X)!",)),
    "safe_mode": (("(o_o)#",), ("(>_<)#",)),
    "task_running": (("(o_o)/",), ("(>_o)-",)),
    "blocked": (("(o_o)⊘",), ("(>_<)⊘",)),
}

_BRIGHTNESS_PRESETS = (64, 128, 192, 255)
_VOLUME_PRESETS = (0, 25, 50, 75, 100)
_MUTE_DURATION_PRESETS = (1, 8, 24)


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_gateway_urls(primary_gateway: str, gateway_urls: object) -> list[str]:
    values: list[str] = []
    if isinstance(gateway_urls, list):
        values.extend(str(item).strip() for item in gateway_urls if isinstance(item, str) and str(item).strip())
    primary = str(primary_gateway).strip()
    if primary:
        values.insert(0, primary)
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped or [primary_gateway]


class HandheldApp:
    def __init__(
        self,
        gateway_url: str,
        device_id: str,
        device_type: str,
        character_size: str | None = None,
        show_progress_messages: bool = True,
        show_celebrations: bool = True,
        brightness: int = 255,
        volume: int = 80,
        led_enabled: bool = True,
        mute_duration_hours: int = 24,
        backend_id: str | None = None,
        agent_id: str | None = None,
        session_key: str | None = None,
        gateway_urls: list[str] | None = None,
        settings_persist: Callable[[dict[str, object]], None] | None = None,
        button_map: dict[str, dict[str, object]] | None = None,
        button_profile_name: str | None = None,
    ) -> None:
        self.gateway_url = gateway_url
        self.device_id = device_id
        self.device_type = device_type

        self.input = Sdl2Input(button_map=button_map)
        self.renderer = Sdl2Renderer()
        self.audio = HandheldAudio()
        self.datp: DatpClient | None = None

        self._ui_mode = UIMode.HOME
        self._online = False
        self._running = True
        self._spinner_frame = 0

        # Card display
        self._card = CardData(title="Oi", body="Welcome")
        self._card_scroll = 0
        self._progress_scroll = 0

        # Canned prompt selection
        self._prompt_idx = 0

        # Recording / audio cache state
        self._recording_stream_id: str | None = None
        self._recording_chunks: list[bytes] = []
        self._recording_format: str = "pcm16"
        self._recording_sample_rate: int = 16000
        self._recording_channels: int = 1
        self._recording_start_time: float = 0.0

        # Outbound mic-stream state
        self._record_tx_stream_id: str | None = None
        self._record_tx_seq: int = 0

        # Per-response audio tracking: maps response_id -> wav_path
        self._response_audio: dict[str, str] = {}

        # Menu
        self._menu_idx = 0
        self._menu_mode = "main"
        self._menu_main_items = ["About Gateway", "Reload", "Reconnect", "Quit"]
        self._menu_settings_items = [
            "Character Size",
            "Brightness",
            "Volume",
            "LED",
            "Mute Duration",
            "Mute",
            "Show Progress",
            "Show Celebrations",
            "Map Buttons",
            "Connection",
            "Diagnostics",
            "System",
            "Back",
        ]
        self._menu_connection_items = ["Gateway", "Backend", "Agent", "Session", "Reconnect Now", "Back"]
        self._menu_system_items = ["Reboot", "Shutdown", "Back"]

        # Delight / easter eggs
        self._secret_tracker = SecretTracker()
        self._surprise_counter = 0

        # X-button press tracking
        self._x_long_press_seen = False
        self._x_pre_recording = False

        # Character display state (default to IDLE placeholder)
        self._character_sprite: str | None = "idle"
        self._character_label: str = "Waiting..."
        self._character_animation: str | None = "idle"
        self._character_overlay_sprite: str | None = None
        self._character_overlay_label: str = ""
        self._character_pack_id: str = ""
        self._character_state: str = "idle"
        size_value = (character_size or os.getenv("OI_CHARACTER_SIZE", "big")).strip().lower()
        if size_value == "mini":
            size_value = "small"
        self._character_size = size_value if size_value in {"big", "small"} else "big"
        self._settings_persist = settings_persist
        self._button_profile_name = button_profile_name or ""
        self._gateway_urls = _normalize_gateway_urls(gateway_url, gateway_urls)
        self._preferred_backend_id = backend_id
        self._preferred_agent_id = agent_id
        self._preferred_session_key = session_key or f"oi:device:{device_id}"
        self._mute_duration_hours = _coerce_int(mute_duration_hours, 24)
        if self._mute_duration_hours not in _MUTE_DURATION_PRESETS:
            self._mute_duration_hours = 24

        # Device command / telemetry state
        self._device_control = DeviceController()
        self._device_control.apply("device.set_brightness", {"value": _coerce_int(brightness, 255)})
        self._device_control.apply("device.set_volume", {"level": _coerce_int(volume, 80)})
        self._device_control.apply("device.set_led", {"enabled": bool(led_enabled)})
        self._telemetry = TelemetryCollector()
        self._next_state_report_at = 0.0
        self._state_report_interval_s = 10.0
        self._command_handlers = {
            "display.show_status": self._handle_display_show_status,
            "display.show_card": self._handle_display_show_card,
            "display.show_progress": self._handle_display_show_progress,
            "display.show_response_delta": self._handle_display_show_response_delta,
            "character.set_state": self._handle_character_set_state,
            "audio.cache.put_begin": self._handle_audio_cache_put_begin,
            "audio.cache.put_chunk": self._handle_audio_cache_put_chunk,
            "audio.cache.put_end": self._handle_audio_cache_put_end,
            "audio.play": self._handle_audio_play,
            "audio.stop": self._handle_audio_stop,
        }
        for op in (
            "device.set_brightness",
            "device.mute_until",
            "device.set_volume",
            "device.set_led",
            "device.reboot",
            "device.shutdown",
            "storage.format",
            "wifi.configure",
        ):
            self._command_handlers[op] = self._handle_device_command

        # Display version
        self._version = self._get_version()
        self._celebration_note = ""
        self._show_progress_messages = bool(show_progress_messages)
        self._show_celebrations = bool(show_celebrations)

    def _get_version(self) -> str:
        """Get git commit hash for display."""
        import subprocess
        import os
        
        # Try multiple possible locations
        possible_paths = [
            "/home/dev/oi-interface",
            "/home/dev/oi-interface/src/oi-clients",
            ".",
            os.path.dirname(__file__) + "/../../../..",
        ]
        
        for path in possible_paths:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    cwd=path,
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()[:8]
            except Exception:
                continue
        
        # Fallback: read from a file if available
        try:
            with open("/etc/oi-version", "r") as f:
                return f.read().strip()[:8]
        except Exception:
            pass
        
        return "dev"


    # ------------------------------------------------------------------
    # Init / Shutdown
    # ------------------------------------------------------------------

    async def run(self) -> None:
        # Init SDL2 subsystems
        if not self.input.init():
            print("Input init failed")
            return
        if not self.renderer.init():
            print("Renderer init failed")
            self.input.shutdown()
            return

        force_mapping = await check_manual_mapping_shortcut(self.renderer, self.input)
        if force_mapping or (not self.input.has_custom_mapping()) or (
            self._button_profile_name and self._button_profile_name != self.input.controller_name()
        ):
            await self._run_button_mapping(force=force_mapping)

        audio_status = self.audio.detect()
        capabilities = self._build_capabilities(audio_status)

        # Show connecting screen
        self._ui_mode = UIMode.CONNECTING
        self._draw_frame()

        # Connect to gateway
        self.datp = DatpClient(
            gateway=self.gateway_url,
            device_id=self.device_id,
            device_type=self.device_type,
            capabilities=capabilities,
            backend_id=self._preferred_backend_id,
            agent_id=self._preferred_agent_id,
            session_key=self._preferred_session_key,
        )
        connected = await self.datp.connect()
        if connected:
            self._sync_connection_preferences_from_server()
            self._online = True
            self._ui_mode = UIMode.READY
            self._card.body = "Select a prompt"
            self._celebration_note = "✨ Gateway handshake complete"
        else:
            self._online = False
            self._ui_mode = UIMode.ERROR
            self._card.body = "Could not connect"

        # Main loop (~30fps)
        while self._running:
            await self._tick()

        logger.warning("Main loop exiting: running=%s ui_mode=%s online=%s", self._running, self._ui_mode, self._online)
        await self.shutdown()

    async def shutdown(self) -> None:
        if self.datp:
            await self.datp.disconnect()
            self.datp = None
        # Clean up temp audio files
        for f in glob.glob("/tmp/oi_audio_*.wav"):
            try:
                os.unlink(f)
            except Exception:
                pass
        self.renderer.shutdown()
        self.input.shutdown()

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    def _build_capabilities(self, audio_status) -> dict:
        cols, rows = self.renderer.effective_text_grid()
        return build_capabilities(audio_status, cols, rows)

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        try:
            # Process input
            for event in self.input.poll():
                logger.debug("input event type=%s name=%s action=%s raw=%s mode=%s", event.type, event.name, event.action, event.raw, self._ui_mode)
                await self._handle_input(event)

            # Process DATP commands
            if self.datp:
                for cmd in self.datp.get_commands():
                    self._handle_command(cmd)
                # Check connection status
                if not self.datp.is_connected and self._online:
                    self._online = False
                    self._ui_mode = UIMode.OFFLINE

            if self._device_control.is_muted() and self._ui_mode == UIMode.READY:
                self._card.title = "Muted"
                self._card.body = f"Muted until {self._device_control.muted_until}"

            await self._maybe_send_state_report()

            # Draw
            self._draw_frame()
            self._spinner_frame += 1

            # Stream recorded audio chunks if actively recording
            await self._stream_recorded_audio()

            # Sleep for ~33ms (30fps)
            await asyncio.sleep(0.033)
        except Exception as exc:
            logger.exception("tick failure: %s", exc)
            self._ui_mode = UIMode.ERROR
            self._card.title = "Runtime error"
            self._card.body = str(exc)

    async def _stream_recorded_audio(self) -> None:
        """Read any newly recorded PCM audio and stream it to gateway."""
        if not self.audio.is_recording:
            return
        chunk = self.audio.read_recording()
        if chunk and self.datp and self.datp.is_connected and self._ui_mode == UIMode.RECORDING:
            stream_id = self._record_tx_stream_id or f"rec_{int(self._recording_start_time * 1000)}"
            await self.datp.send_audio_chunk(stream_id, self._record_tx_seq, chunk, 16000)
            self._record_tx_seq += 1
            self._card.title = "Recording"
            self._card.body = f"Streaming audio… {len(chunk)} bytes"

    async def _maybe_send_state_report(self) -> None:
        if not self.datp or not self.datp.is_connected:
            return
        now = time.time()
        if now < self._next_state_report_at:
            return
        audio_cache_used_bytes = sum(
            os.path.getsize(path)
            for path in self._response_audio.values()
            if os.path.exists(path)
        )
        payload = self._telemetry.collect(
            mode=self._current_state().value,
            muted_until=self._device_control.muted_until,
            audio_cache_used_bytes=audio_cache_used_bytes,
        )
        await self.datp.send_state_report(**payload)
        self._next_state_report_at = now + self._state_report_interval_s

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    async def _handle_input(self, ev: InputEvent) -> None:
        if ev.type == "quit":
            # SDL_QUIT can be emitted spuriously on some handheld stacks.
            # Ignore it in-device and rely on explicit menu Quit instead.
            logger.warning("Ignoring SDL quit event")
            return

        # Handle long-press recording controls before generic pressed gating.
        if ev.name == "x" and ev.action == "pressed" and self._ui_mode in (UIMode.HOME, UIMode.READY):
            if self._device_control.is_muted():
                self._card.title = "Muted"
                self._card.body = f"Muted until {self._device_control.muted_until}"
                self._ui_mode = UIMode.CARD
                return
            # Start capture immediately so early speech isn't lost; only publish if long-press confirms.
            self._card.title = "Voice"
            self._card.body = "Hold X…"
            if not self.audio.is_recording:
                if self.audio.recording_init() and self.audio.start_recording():
                    self._x_pre_recording = True
                else:
                    self._card.title = "Voice"
                    self._card.body = "Mic not available"
                    self._ui_mode = UIMode.ERROR
            return

        if ev.name == "x" and ev.action == "long_press" and self._ui_mode in (UIMode.HOME, UIMode.READY):
            self._x_long_press_seen = True
            ok = await self.start_recording()
            if not ok and not self._device_control.is_muted():
                self._card.title = "Voice"
                self._card.body = "Mic not available"
                self._ui_mode = UIMode.ERROR
            return
        if ev.name == "x" and ev.action == "long_release" and self.audio.is_recording:
            await self.stop_recording()
            self._x_long_press_seen = False
            return

        # Short-press A should fire on release, not press, to avoid accidental sends.
        if ev.name == "a" and ev.action == "released" and self._ui_mode in (UIMode.HOME, UIMode.READY):
            if self._ui_mode != UIMode.RECORDING:
                prompt = self._selected_prompt()
                await self._send_prompt(prompt)
            return

        # Reset long-press guard when X is released without recording active.
        if ev.name == "x" and ev.action == "released":
            # If long-press wasn't reached, discard any speculative pre-recording.
            if not self._x_long_press_seen and self.audio.is_recording:
                self.audio.stop_recording()
                self._x_pre_recording = False
            if not self.audio.is_recording and self._ui_mode in (UIMode.HOME, UIMode.READY):
                self._card.title = "Oi"
                self._card.body = "Select a prompt"
            self._x_long_press_seen = False
            return

        if ev.action != "pressed":
            return

        if self._ui_mode in (UIMode.HOME, UIMode.READY) and self._secret_tracker.push(ev.name):
            self._card.title = "Blob Party"
            self._card.body = "Secret code accepted.\n\nThe handheld feels 12% more magical now."
            self._ui_mode = UIMode.CARD
            self._celebration_note = "🎈 Party mode ready"
            return

        if self._ui_mode == UIMode.MENU:
            await self._handle_menu(ev.name)
            return

        if ev.name == "start":
            self._ui_mode = UIMode.MENU
            self._menu_mode = "main"
            self._menu_idx = 0
            return

        if ev.name == "select":
            self._ui_mode = UIMode.MENU
            self._menu_mode = "settings"
            self._menu_idx = 0
            return

        if self._ui_mode in (UIMode.HOME, UIMode.READY):
            if ev.name == "b":
                if self._ui_mode == UIMode.RECORDING:
                    # Cancel recording
                    await self.stop_recording()
                    self._ui_mode = UIMode.HOME if self._online else UIMode.OFFLINE
                # else: no-op in home
            elif ev.name == "up":
                self._prompt_idx = (self._prompt_idx - 1) % len(CANNED_PROMPTS)
            elif ev.name == "down":
                self._prompt_idx = (self._prompt_idx + 1) % len(CANNED_PROMPTS)

        elif self._ui_mode == UIMode.CARD:
            if ev.name == "a":
                if self._device_control.is_muted():
                    self._card.title = "Muted"
                    self._card.body = f"Muted until {self._device_control.muted_until}"
                    return
                last_response = list(self._response_audio.keys())[-1] if self._response_audio else "latest"
                wav_path = self._response_audio.get(last_response)
                if wav_path and os.path.exists(wav_path):
                    self.audio.play(wav_path)
            elif ev.name == "b":
                self._ui_mode = UIMode.HOME
                self._card_scroll = 0
            elif ev.name == "up":
                self._card_scroll = max(0, self._card_scroll - 20)
            elif ev.name == "down":
                max_scroll = self._max_card_scroll(self._card.title, self._card.body)
                self._card_scroll = min(max_scroll, self._card_scroll + 20)

        elif self._ui_mode == UIMode.WAITING:
            if ev.name == "b":
                self._ui_mode = UIMode.HOME

        elif self._ui_mode == UIMode.ERROR or self._ui_mode == UIMode.OFFLINE:
            if ev.name == "a":
                # Retry connect
                self._ui_mode = UIMode.CONNECTING
                if self.datp:
                    ok = await self.datp.reconnect()
                    if ok:
                        self._sync_connection_preferences_from_server()
                    self._online = ok
                    self._ui_mode = UIMode.READY if ok else UIMode.ERROR
            elif ev.name == "b":
                logger.warning("Exiting due to B in %s mode", self._ui_mode)
                self._running = False

    def _cycle_preset(self, current: int, presets: tuple[int, ...]) -> int:
        for preset in presets:
            if current < preset:
                return preset
        return presets[0]

    def _brightness_label(self) -> str:
        return f"{round((self._device_control.brightness / 255) * 100):d}%"

    def _mute_duration_label(self) -> str:
        return f"{self._mute_duration_hours}h"

    def _available_backends(self) -> list[dict[str, str]]:
        payload = self.datp.server_info.get("payload", {}) if self.datp and self.datp.server_info else {}
        items = payload.get("available_backends") if isinstance(payload, dict) else []
        return [item for item in items if isinstance(item, dict) and item.get("id")]

    def _available_agents(self) -> list[dict[str, str]]:
        payload = self.datp.server_info.get("payload", {}) if self.datp and self.datp.server_info else {}
        items = payload.get("available_agents") if isinstance(payload, dict) else []
        return [item for item in items if isinstance(item, dict) and (item.get("id") or item.get("name"))]

    def _current_gateway_label(self) -> str:
        return self.gateway_url

    def _current_backend_label(self) -> str:
        current = self._preferred_backend_id
        for item in self._available_backends():
            if item.get("id") == current:
                return str(item.get("name") or current)
        return current or "default"

    def _current_agent_label(self) -> str:
        current = self._preferred_agent_id
        for item in self._available_agents():
            item_id = str(item.get("id") or item.get("name"))
            if item_id == current:
                return str(item.get("name") or item_id)
        return current or "default"

    def _current_session_label(self) -> str:
        value = self._preferred_session_key or f"oi:device:{self.device_id}"
        if value == f"oi:device:{self.device_id}":
            return "device"
        return value.replace("oi:session:", "session:")

    async def _apply_connection_preferences(self, *, reconnect: bool = True, allow_live_update: bool = True) -> bool:
        if self.datp:
            self.datp.set_gateway(self.gateway_url)
            self.datp.update_conversation(
                backend_id=self._preferred_backend_id,
                agent_id=self._preferred_agent_id,
                session_key=self._preferred_session_key,
            )
        self._persist_settings()
        if reconnect and self.datp:
            self._ui_mode = UIMode.CONNECTING
            if allow_live_update and self.datp.is_connected:
                try:
                    response = await self.datp.send_conversation_update(
                        backend_id=self._preferred_backend_id,
                        agent_id=self._preferred_agent_id,
                        session_key=self._preferred_session_key,
                        await_reply=True,
                    )
                    if isinstance(response, dict) and response.get("type") == "error":
                        self._online = True
                        self._ui_mode = UIMode.ERROR
                        self._card.title = "Connection update failed"
                        self._card.body = str((response.get("payload") or {}).get("message") or "Gateway rejected connection update")
                        return False
                    self._sync_connection_preferences_from_server()
                    self._online = True
                    self._ui_mode = UIMode.READY
                    self._card.body = "Connection updated"
                    return True
                except Exception:
                    pass
            ok = await self.datp.reconnect()
            if ok:
                self._sync_connection_preferences_from_server()
            self._online = ok
            self._ui_mode = UIMode.READY if ok else UIMode.ERROR
            if ok:
                self._card.body = "Connection updated"
            return ok
        return True

    def _reset_connection_preferences_for_gateway(self) -> None:
        self._preferred_backend_id = None
        self._preferred_agent_id = None
        self._preferred_session_key = f"oi:device:{self.device_id}"

    def _cycle_gateway(self) -> str:
        if self.gateway_url not in self._gateway_urls:
            self._gateway_urls.append(self.gateway_url)
        current_url = self.gateway_url
        next_url = self._gateway_urls[(self._gateway_urls.index(self.gateway_url) + 1) % len(self._gateway_urls)]
        self.gateway_url = next_url
        if next_url != current_url:
            self._reset_connection_preferences_for_gateway()
        return self._current_gateway_label()

    def _cycle_backend(self) -> str:
        backends = self._available_backends()
        if not backends:
            return self._preferred_backend_id or "default"
        ids = [str(item["id"]) for item in backends]
        if not self._preferred_backend_id or self._preferred_backend_id not in ids:
            self._preferred_backend_id = ids[0]
            return self._current_backend_label()
        next_id = ids[(ids.index(self._preferred_backend_id) + 1) % len(ids)]
        self._preferred_backend_id = next_id
        return self._current_backend_label()

    def _cycle_agent(self) -> str:
        agents = self._available_agents()
        if not agents:
            return self._preferred_agent_id or "default"
        ids = [str(item.get("id") or item.get("name")) for item in agents]
        if not self._preferred_agent_id or self._preferred_agent_id not in ids:
            self._preferred_agent_id = ids[0]
            return self._current_agent_label()
        next_id = ids[(ids.index(self._preferred_agent_id) + 1) % len(ids)]
        self._preferred_agent_id = next_id
        return self._current_agent_label()

    def _cycle_session(self) -> str:
        default_session = f"oi:device:{self.device_id}"
        current = self._preferred_session_key or default_session
        if current == default_session:
            self._preferred_session_key = f"oi:session:{uuid.uuid4().hex[:8]}"
        else:
            self._preferred_session_key = default_session
        return self._current_session_label()

    def _sync_connection_preferences_from_server(self) -> None:
        server_info = getattr(self.datp, "server_info", None) if self.datp else None
        payload = server_info.get("payload", {}) if isinstance(server_info, dict) else {}
        if not isinstance(payload, dict):
            return
        if payload.get("selected_backend"):
            self._preferred_backend_id = str(payload["selected_backend"])
        selected_agent = payload.get("selected_agent")
        if isinstance(selected_agent, dict) and (selected_agent.get("id") or selected_agent.get("name")):
            self._preferred_agent_id = str(selected_agent.get("id") or selected_agent.get("name"))
        elif payload.get("default_agent") and isinstance(payload["default_agent"], dict):
            self._preferred_agent_id = str(payload["default_agent"].get("id") or payload["default_agent"].get("name") or self._preferred_agent_id)
        if payload.get("selected_session_key"):
            self._preferred_session_key = str(payload["selected_session_key"])

    def _restore_connection_state(
        self,
        *,
        gateway_url: str,
        backend_id: str | None,
        agent_id: str | None,
        session_key: str | None,
    ) -> None:
        self.gateway_url = gateway_url
        self._preferred_backend_id = backend_id
        self._preferred_agent_id = agent_id
        self._preferred_session_key = session_key
        if self.datp:
            self.datp.set_gateway(gateway_url)
            self.datp.update_conversation(
                backend_id=backend_id,
                agent_id=agent_id,
                session_key=session_key,
            )
        self._persist_settings()

    def _show_card_message(self, title: str, body: str) -> None:
        self._card.title = title
        self._card.body = body
        self._card_scroll = 0
        self._ui_mode = UIMode.CARD

    def _show_diagnostics(self) -> None:
        telemetry = self._telemetry.collect(
            mode=self._ui_mode.value,
            muted_until=self._device_control.muted_until,
            audio_cache_used_bytes=sum(os.path.getsize(path) for path in self._response_audio.values() if os.path.exists(path)),
        )
        lines = [
            f"online: {'yes' if self._online else 'no'}",
            f"gateway: {self._current_gateway_label()}",
            f"backend: {self._current_backend_label()}",
            f"agent: {self._current_agent_label()}",
            f"session: {self._current_session_label()}",
            f"controller: {self.input.controller_name()}",
            f"button map: {'custom' if self.input.has_custom_mapping() else 'default'}",
            f"profile: {self._button_profile_name or 'unset'}",
            f"brightness: {self._brightness_label()} ({self._device_control.brightness})",
            f"volume: {self._device_control.volume}%",
            f"led: {'on' if self._device_control.led_enabled else 'off'}",
            f"mute preset: {self._mute_duration_label()}",
            f"muted: {self._device_control.muted_until or 'no'}",
            f"audio cache files: {len(self._response_audio)}",
        ]
        if "battery_percent" in telemetry:
            lines.append(f"battery: {telemetry['battery_percent']}%")
        if "charging" in telemetry:
            lines.append(f"charging: {'yes' if telemetry['charging'] else 'no'}")
        if "wifi_rssi" in telemetry:
            lines.append(f"wifi: {telemetry['wifi_rssi']} dBm")
        if "heap_free" in telemetry:
            lines.append(f"free mem: {telemetry['heap_free']}")
        lines.append(f"uptime: {telemetry.get('uptime_s', 0)}s")
        self._show_card_message("Diagnostics", "\n".join(lines))

    async def _run_button_mapping(self, *, force: bool) -> None:
        seed_map = self.input.export_button_map()
        mapped = await run_button_mapping_wizard(self.renderer, self.input, seed_map=seed_map)
        if mapped:
            self.input.set_button_map(mapped, custom=True)
            self._button_profile_name = self.input.controller_name()
            self._persist_settings()
            status = "updated" if force else "saved"
            self._show_card_message("Button Setup", f"Button profile {status} for {self._button_profile_name}")
        elif force:
            self._show_card_message("Button Setup", "Mapping cancelled; keeping current button profile")

    async def _handle_menu(self, name: str) -> None:
        menu_items = self._menu_items()
        if name == "a":
            item = menu_items[self._menu_idx]
            if item == "About Gateway":
                self._show_card_message("Gateway", "\n".join(format_gateway_about(self.datp.server_info if self.datp else None)))
            elif item == "Character Size":
                self._character_size = "small" if self._character_size == "big" else "big"
                self._persist_settings()
                self._show_card_message("Character Size", f"Set to {self._character_size}")
            elif item == "Brightness":
                value = self._cycle_preset(self._device_control.brightness, _BRIGHTNESS_PRESETS)
                self._device_control.apply("device.set_brightness", {"value": value})
                self._persist_settings()
                self._show_card_message("Brightness", f"Set to {self._brightness_label()} ({value})")
            elif item == "Volume":
                value = self._cycle_preset(self._device_control.volume, _VOLUME_PRESETS)
                self._device_control.apply("device.set_volume", {"level": value})
                self._persist_settings()
                self._show_card_message("Volume", f"Set to {self._device_control.volume}%")
            elif item == "LED":
                enabled = not self._device_control.led_enabled
                self._device_control.apply("device.set_led", {"enabled": enabled})
                self._persist_settings()
                self._show_card_message("LED", f"Set to {'on' if enabled else 'off'}")
            elif item == "Mute Duration":
                self._mute_duration_hours = self._cycle_preset(self._mute_duration_hours, _MUTE_DURATION_PRESETS)
                self._persist_settings()
                self._show_card_message("Mute Duration", f"Set to {self._mute_duration_label()}")
            elif item == "Mute":
                if self._device_control.is_muted():
                    self._device_control.clear_mute()
                    self._show_card_message("Mute", "Audio unmuted")
                else:
                    until = (datetime.now(timezone.utc) + timedelta(hours=self._mute_duration_hours)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
                    self._device_control.apply("device.mute_until", {"until": until})
                    self.audio.stop()
                    self._show_card_message("Mute", f"Muted until {self._device_control.muted_until}")
            elif item == "Show Progress":
                self._show_progress_messages = not self._show_progress_messages
                self._persist_settings()
                self._show_card_message("Show Progress", f"Set to {'on' if self._show_progress_messages else 'off'}")
            elif item == "Show Celebrations":
                self._show_celebrations = not self._show_celebrations
                if not self._show_celebrations:
                    self._celebration_note = ""
                self._persist_settings()
                self._show_card_message("Show Celebrations", f"Set to {'on' if self._show_celebrations else 'off'}")
            elif item == "Map Buttons":
                await self._run_button_mapping(force=True)
            elif item == "Connection":
                self._menu_mode = "connection"
                self._menu_idx = 0
            elif item == "Diagnostics":
                self._show_diagnostics()
            elif item == "System":
                self._menu_mode = "system"
                self._menu_idx = 0
            elif item == "Reload":
                await self._reload_process()
            elif item == "Quit":
                logger.warning("Exiting due to menu Quit")
                self._running = False
            elif item == "Reconnect":
                self._ui_mode = UIMode.CONNECTING
                if self.datp:
                    try:
                        await self.datp.reconnect()
                    except Exception as exc:
                        self._online = False
                        self._ui_mode = UIMode.ERROR
                        self._card.title = "Reconnect failed"
                        self._card.body = str(exc)
                        return
                    if self.datp.is_connected:
                        self._sync_connection_preferences_from_server()
                    self._online = self.datp.is_connected
                    self._ui_mode = UIMode.READY if self._online else UIMode.ERROR
            elif item == "Gateway":
                previous = (self.gateway_url, self._preferred_backend_id, self._preferred_agent_id, self._preferred_session_key)
                label = self._cycle_gateway()
                if await self._apply_connection_preferences(reconnect=True, allow_live_update=False):
                    self._show_card_message("Gateway", f"Set to {label}")
                else:
                    self._restore_connection_state(
                        gateway_url=previous[0],
                        backend_id=previous[1],
                        agent_id=previous[2],
                        session_key=previous[3],
                    )
                    if self.datp:
                        self._ui_mode = UIMode.CONNECTING
                        try:
                            restored_ok = await self.datp.reconnect()
                        except Exception as exc:
                            self._online = False
                            self._ui_mode = UIMode.ERROR
                            self._card.title = "Gateway switch failed"
                            self._card.body = str(exc)
                            return
                        if restored_ok:
                            self._sync_connection_preferences_from_server()
                            self._online = True
                            self._show_card_message("Gateway", f"Stayed on {previous[0]}")
                        else:
                            self._online = False
                            self._ui_mode = UIMode.ERROR
                            self._card.title = "Gateway switch failed"
                            self._card.body = f"Could not reach {label}; restored {previous[0]}" 
            elif item == "Backend":
                previous = (self._preferred_backend_id, self._preferred_agent_id, self._preferred_session_key)
                label = self._cycle_backend()
                if await self._apply_connection_preferences(reconnect=True):
                    self._show_card_message("Backend", f"Set to {label}")
                else:
                    self._restore_connection_state(
                        gateway_url=self.gateway_url,
                        backend_id=previous[0],
                        agent_id=previous[1],
                        session_key=previous[2],
                    )
            elif item == "Agent":
                previous = (self._preferred_backend_id, self._preferred_agent_id, self._preferred_session_key)
                label = self._cycle_agent()
                if await self._apply_connection_preferences(reconnect=True):
                    self._show_card_message("Agent", f"Set to {label}")
                else:
                    self._restore_connection_state(
                        gateway_url=self.gateway_url,
                        backend_id=previous[0],
                        agent_id=previous[1],
                        session_key=previous[2],
                    )
            elif item == "Session":
                previous = (self._preferred_backend_id, self._preferred_agent_id, self._preferred_session_key)
                label = self._cycle_session()
                if await self._apply_connection_preferences(reconnect=True):
                    self._show_card_message("Session", f"Set to {label}")
                else:
                    self._restore_connection_state(
                        gateway_url=self.gateway_url,
                        backend_id=previous[0],
                        agent_id=previous[1],
                        session_key=previous[2],
                    )
            elif item == "Reconnect Now":
                await self._apply_connection_preferences(reconnect=True, allow_live_update=False)
            elif item == "Reboot":
                result = self._device_control.apply("device.reboot")
                self._show_card_message("Reboot", result.message or ("ok" if result.ok else "reboot blocked"))
            elif item == "Shutdown":
                result = self._device_control.apply("device.shutdown")
                self._show_card_message("Shutdown", result.message or ("ok" if result.ok else "shutdown blocked"))
            elif item == "Back":
                if self._menu_mode in {"system", "connection"}:
                    self._menu_mode = "settings"
                else:
                    self._menu_mode = "main"
                self._menu_idx = 0
        elif name == "b":
            if self._menu_mode in {"system", "connection"}:
                self._menu_mode = "settings"
                self._menu_idx = 0
            elif self._menu_mode == "settings":
                self._menu_mode = "main"
                self._menu_idx = 0
            else:
                self._ui_mode = UIMode.HOME
        elif name == "up":
            self._menu_idx = (self._menu_idx - 1) % len(menu_items)
        elif name == "down":
            self._menu_idx = (self._menu_idx + 1) % len(menu_items)

    def _menu_items(self) -> list[str]:
        if self._menu_mode == "settings":
            return self._menu_settings_items
        if self._menu_mode == "connection":
            return self._menu_connection_items
        if self._menu_mode == "system":
            return self._menu_system_items
        return self._menu_main_items

    def _persist_settings(self) -> None:
        if self._settings_persist is None:
            return
        try:
            self._settings_persist({
                "character_size": self._character_size,
                "show_progress_messages": self._show_progress_messages,
                "show_celebrations": self._show_celebrations,
                "brightness": self._device_control.brightness,
                "volume": self._device_control.volume,
                "led_enabled": self._device_control.led_enabled,
                "mute_duration_hours": self._mute_duration_hours,
                "gateway_url": self.gateway_url,
                "gateway_urls": list(self._gateway_urls),
                "backend_id": self._preferred_backend_id,
                "agent_id": self._preferred_agent_id,
                "session_key": self._preferred_session_key,
                "button_map": self.input.export_button_map(),
                "button_profile_name": self._button_profile_name,
            })
        except Exception as exc:
            logger.warning("settings persistence failed: %s", exc)

    def _selected_prompt(self) -> str:
        choice = CANNED_PROMPTS[self._prompt_idx]
        if choice == SURPRISE_LABEL:
            prompt = pick_surprise_prompt(self._surprise_counter)
            self._surprise_counter += 1
            return prompt
        return choice

    async def _send_prompt(self, text: str) -> None:
        if self._device_control.is_muted():
            self._card.title = "Muted"
            self._card.body = f"Muted until {self._device_control.muted_until}"
            self._ui_mode = UIMode.CARD
            return
        if not self.datp or not self.datp.is_connected:
            self._ui_mode = UIMode.OFFLINE
            return
        # Clear previous response before sending new prompt
        self._card = CardData(title="Oi", body=pick_waiting_quip(self._spinner_frame))
        self._ui_mode = UIMode.WAITING
        # Optimistic local character update so UI reflects waiting immediately.
        self._character_label = "Waiting"
        self._character_animation = "pulse"
        self._celebration_note = ""
        try:
            await self.datp.send_text_prompt(text)
        except Exception as exc:
            self._ui_mode = UIMode.ERROR
            self._card.title = "Send failed"
            self._card.body = str(exc)

    # ------------------------------------------------------------------
    # Command handling (from gateway)
    # ------------------------------------------------------------------

    def _handle_command(self, cmd: dict) -> bool:
        op = cmd.get("op", "")
        args = cmd.get("args", {})
        handler = self._command_handlers.get(op)
        if handler is None:
            logger.warning("Unhandled gateway command: %s", op)
            return False
        return bool(handler(op, args))

    def _handle_display_show_status(self, _op: str, args: dict) -> bool:
        state = args.get("state", "")
        label = args.get("label", "")
        if state:
            self._character_state = str(state).lower()
        self._ui_mode = self._state_to_ui(state)
        self._card.title = state.capitalize() if state else "Oi"
        if label:
            self._card.body = label
        return True

    def _handle_display_show_card(self, _op: str, args: dict) -> bool:
        self._card.title = args.get("title", "Response")
        body = args.get("body", "")
        if self._card.title.lower() == "response" and self._show_celebrations:
            self._celebration_note = pick_celebration(len(body))
            if self._celebration_note:
                body = body + ("\n\n" if body else "") + self._celebration_note
        self._card.body = body
        self._card_scroll = 0
        self._ui_mode = UIMode.CARD
        return True

    def _handle_display_show_progress(self, _op: str, args: dict) -> bool:
        text = (args.get("text", "") or "").strip()
        if text and self._ui_mode == UIMode.WAITING:
            if not self._show_progress_messages:
                return True
            self._card.title = "Working"
            body = self._card.body or ""
            self._card.body = (body + ("\n" if body else "") + f"• {text}")[-1200:]
            self._progress_scroll = self._max_card_scroll("Waiting", self._card.body)
        return True

    def _handle_display_show_response_delta(self, _op: str, args: dict) -> bool:
        text_delta = args.get("text_delta", "")
        is_final = bool(args.get("is_final", False))
        if text_delta:
            if self._ui_mode != UIMode.CARD or self._card.title != "Response":
                self._card.title = "Response"
                self._card.body = ""
                self._card_scroll = 0
            self._card.body = (self._card.body or "") + text_delta
        if is_final:
            if self._show_celebrations:
                self._celebration_note = pick_celebration(len(self._card.body))
                if self._celebration_note and self._celebration_note not in self._card.body:
                    self._card.body = (self._card.body or "") + "\n\n" + self._celebration_note
            self._card_scroll = 0
            self._ui_mode = UIMode.CARD
        elif self._ui_mode == UIMode.WAITING and text_delta:
            self._ui_mode = UIMode.CARD
        return True

    def _handle_character_set_state(self, _op: str, args: dict) -> bool:
        self._character_sprite = args.get("sprite")
        self._character_label = args.get("label", "")
        self._character_animation = args.get("animation")
        self._character_overlay_sprite = args.get("overlay")
        self._character_overlay_label = args.get("overlay_label", "")
        self._character_pack_id = args.get("pack_id", "")
        mapped_state = self._state_from_sprite(self._character_sprite)
        if mapped_state:
            self._character_state = mapped_state
        return True

    def _handle_audio_cache_put_begin(self, _op: str, args: dict) -> bool:
        self._recording_stream_id = args.get("stream_id", f"stream_{uuid.uuid4().hex[:8]}")
        self._recording_chunks = []
        self._recording_format = str(args.get("format", "pcm16") or "pcm16").lower()
        self._recording_sample_rate = _coerce_int(args.get("sample_rate", 24000) or 24000, 24000)
        self._recording_channels = _coerce_int(args.get("channels", 1) or 1, 1)
        if not self._device_control.is_muted() and self._recording_format not in {"wav", "audio/wav", "wave"}:
            self.audio.start_pcm_stream(sample_rate=self._recording_sample_rate, channels=self._recording_channels)
        logger.info(
            "audio.begin stream_id=%s response_id=%s format=%s sr=%s ch=%s",
            self._recording_stream_id,
            args.get("response_id", "latest"),
            self._recording_format,
            self._recording_sample_rate,
            self._recording_channels,
        )
        return True

    def _handle_audio_cache_put_chunk(self, _op: str, args: dict) -> bool:
        import base64
        try:
            chunk = base64.b64decode(args.get("data_b64", ""))
        except Exception:
            chunk = b""
        if not chunk:
            return False
        self._recording_chunks.append(chunk)
        if not self._device_control.is_muted() and self._recording_format not in {"wav", "audio/wav", "wave"}:
            self.audio.write_pcm_stream(chunk)
        logger.debug(
            "audio.chunk stream_id=%s seq=%s bytes=%d total_chunks=%d",
            self._recording_stream_id,
            args.get("seq"),
            len(chunk),
            len(self._recording_chunks),
        )
        return True

    def _handle_audio_cache_put_end(self, _op: str, args: dict) -> bool:
        if not self._recording_chunks:
            self.audio.end_pcm_stream()
            logger.warning("audio.end with no chunks stream_id=%s response_id=%s", self._recording_stream_id, args.get("response_id", "latest"))
            self._card.title = "Audio"
            self._card.body = "No audio chunks received"
            self._ui_mode = UIMode.CARD
            return False

        combined = b"".join(self._recording_chunks)
        fmt = self._recording_format
        is_wav_container = fmt in {"wav", "audio/wav", "wave"}

        if is_wav_container:
            fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="oi_audio_")
            with os.fdopen(fd, "wb") as fh:
                fh.write(combined)
            wav = wav_path
        else:
            wav = str(self.audio.save_wav(
                combined,
                sample_rate=self._recording_sample_rate,
                channels=self._recording_channels,
            ))

        self.audio.end_pcm_stream()
        response_id = args.get("response_id", "latest")
        self._response_audio[response_id] = wav
        logger.info(
            "audio.end stream_id=%s response_id=%s format=%s chunks=%d total_bytes=%d wav=%s",
            self._recording_stream_id,
            response_id,
            fmt,
            len(self._recording_chunks),
            len(combined),
            wav,
        )
        logger.info("audio.cached response_id=%s path=%s (live stream already started)", response_id, wav)
        self._recording_chunks = []
        return True

    def _handle_audio_play(self, _op: str, args: dict) -> bool:
        if self._device_control.is_muted():
            self.audio.stop()
            self._card.title = "Muted"
            self._card.body = f"Muted until {self._device_control.muted_until}"
            self._ui_mode = UIMode.CARD
            return True
        response_id = args.get("response_id", "latest")
        wav_path = self._response_audio.get(response_id)
        if wav_path and os.path.exists(wav_path):
            return self.audio.play(wav_path)
        if response_id == "latest" and self._response_audio:
            last_wav = list(self._response_audio.values())[-1]
            if os.path.exists(last_wav):
                return self.audio.play(last_wav)
        return False

    def _handle_audio_stop(self, _op: str, _args: dict) -> bool:
        self.audio.stop()
        return True

    def _handle_device_command(self, op: str, args: dict) -> bool:
        result = self._device_control.apply(op, args)
        if op == "device.mute_until" and result.ok:
            self.audio.stop()
            self._ui_mode = UIMode.HOME
        if not result.ok:
            logger.warning("Device command %s failed: %s", op, result.message)
        else:
            logger.info("Device command %s: %s", op, result.message)
        return result.ok
    def _state_to_ui(self, state: str) -> UIMode:
        mapping = {
            "idle": UIMode.READY,
            "listening": UIMode.RECORDING,
            "thinking": UIMode.WAITING,
            "response_cached": UIMode.CARD,
            "playing": UIMode.CARD,
            "muted": UIMode.HOME,
            "offline": UIMode.OFFLINE,
            "error": UIMode.ERROR,
        }
        return mapping.get(state.lower(), UIMode.HOME)

    def _current_state(self) -> State:
        if self._ui_mode == UIMode.CONNECTING:
            return State.BOOTING
        if self._ui_mode == UIMode.RECORDING:
            return State.RECORDING
        if self._ui_mode == UIMode.WAITING:
            return State.THINKING
        if self._ui_mode == UIMode.OFFLINE:
            return State.OFFLINE
        if self._ui_mode == UIMode.ERROR:
            return State.ERROR
        if self._device_control.is_muted():
            return State.MUTED
        if self.audio.is_playing():
            return State.PLAYING
        if self._ui_mode == UIMode.CARD:
            return State.RESPONSE_CACHED
        return State.READY

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _draw_frame(self) -> None:
        self.renderer.clear()
        blob = self._ascii_blob_lines()

        # Title bar with connection status
        title = "Oi — " + self._ui_mode.value.upper()
        self.renderer.draw_title(title, online=self._online)

        # Character display (if available) - drawn between title bar and main content
        self._draw_character()

        # Main content area based on mode
        if self._ui_mode == UIMode.CONNECTING:
            self.renderer.draw_card("Connecting", [pick_connecting_quip(self._spinner_frame), f"Attempting to reach {self.gateway_url}..."], 0, ascii_bg_lines=blob)
            self.renderer.draw_spinner(self.width_center(40), self.renderer.spinner_y(), self._spinner_frame)

        elif self._ui_mode == UIMode.READY or self._ui_mode == UIMode.HOME:
            if self._device_control.is_muted():
                lines = [f"Muted until {self._device_control.muted_until or 'unknown'}", "", "Gateway commands still sync."]
                self.renderer.draw_card("Muted", lines, 0, ascii_bg_lines=blob)
            else:
                lines = ["Select a prompt:"] + [f"  {'>' if i == self._prompt_idx else ' '} {p}" for i, p in enumerate(CANNED_PROMPTS)]
                if self._celebration_note:
                    lines += ["", self._celebration_note]
                self.renderer.draw_card("Home", lines, 0, ascii_bg_lines=blob)

        elif self._ui_mode == UIMode.WAITING:
            # While waiting, show live progress and keep newest entries on screen.
            waiting_lines = [pick_waiting_quip(self._spinner_frame), "Sending to gateway..."]
            if self._card.body:
                body_lines = [ln for ln in self._card.body.split("\n") if ln.strip()]
                if body_lines:
                    waiting_lines = body_lines
            progress_body = "\n".join(waiting_lines)
            self._progress_scroll = self._max_card_scroll("Waiting", progress_body)
            self.renderer.draw_card("Waiting", waiting_lines, self._progress_scroll, ascii_bg_lines=blob)
            self.renderer.draw_spinner(self.width_center(40), self.renderer.spinner_y(), self._spinner_frame)

        elif self._ui_mode == UIMode.CARD:
            body_lines = self._card.body.split("\n")
            self.renderer.draw_card(self._card.title, body_lines, self._card_scroll, ascii_bg_lines=blob)

        elif self._ui_mode == UIMode.MENU:
            lines = []
            menu_items = self._menu_items()
            for i, item in enumerate(menu_items):
                marker = "> " if i == self._menu_idx else "  "
                if item == "Character Size":
                    lines.append(f"{marker}{item}: {self._character_size}")
                elif item == "Brightness":
                    lines.append(f"{marker}{item}: {self._brightness_label()}")
                elif item == "Volume":
                    lines.append(f"{marker}{item}: {self._device_control.volume}%")
                elif item == "LED":
                    lines.append(f"{marker}{item}: {'on' if self._device_control.led_enabled else 'off'}")
                elif item == "Mute Duration":
                    lines.append(f"{marker}{item}: {self._mute_duration_label()}")
                elif item == "Mute":
                    lines.append(f"{marker}{item}: {'on' if self._device_control.is_muted() else 'off'}")
                elif item == "Show Progress":
                    lines.append(f"{marker}{item}: {'on' if self._show_progress_messages else 'off'}")
                elif item == "Show Celebrations":
                    lines.append(f"{marker}{item}: {'on' if self._show_celebrations else 'off'}")
                elif item == "Gateway":
                    lines.append(f"{marker}{item}: {self._current_gateway_label()}")
                elif item == "Backend":
                    lines.append(f"{marker}{item}: {self._current_backend_label()}")
                elif item == "Agent":
                    lines.append(f"{marker}{item}: {self._current_agent_label()}")
                elif item == "Session":
                    lines.append(f"{marker}{item}: {self._current_session_label()}")
                else:
                    lines.append(f"{marker}{item}")
            menu_title = "Settings" if self._menu_mode == "settings" else "Connection" if self._menu_mode == "connection" else "System" if self._menu_mode == "system" else "Menu"
            self.renderer.draw_card(menu_title, lines, 0, ascii_bg_lines=blob)

        elif self._ui_mode == UIMode.ERROR:
            url = getattr(self, 'gateway_url', '?')
            body_lines = [
                self._card.body,
                "",
                f"URL: {url}",
                "",
                "A: Retry  B: Quit",
            ]
            self.renderer.draw_card("Error", body_lines, 0, ascii_bg_lines=blob)

        elif self._ui_mode == UIMode.OFFLINE:
            url = getattr(self, 'gateway_url', '?')
            body_lines = [
                "Gateway unreachable.",
                "",
                f"URL: {url}",
                "",
                "A: Retry  B: Quit",
            ]
            self.renderer.draw_card("Offline", body_lines, 0, ascii_bg_lines=blob)

        # Bottom hints
        hints = self._hint_for_mode()
        # Show recording indicator if actively capturing
        if self._ui_mode == UIMode.RECORDING:
            self.renderer.draw_recording_indicator()
        self.renderer.draw_hints(hints, self._version)

        self.renderer.present()

    def _ascii_blob_lines(self) -> list[str]:
        """Return state-driven ASCII character art (big or small)."""
        frame_index = int(time.time() * 3.0) % 2
        state = self._current_ascii_state()
        frames = self._ascii_frames(state, self._character_size)
        return list(frames[frame_index])

    def _current_ascii_state(self) -> str:
        state = self._character_state.strip().lower() if self._character_state else ""
        if state in _ASCII_STATES:
            return state
        if self._ui_mode == UIMode.RECORDING:
            return "listening"
        if self._ui_mode == UIMode.WAITING:
            return "thinking"
        if self._ui_mode == UIMode.CARD and self.audio.is_playing():
            return "playing"
        if self._ui_mode == UIMode.CARD:
            return "response_cached"
        if self._ui_mode == UIMode.OFFLINE:
            return "offline"
        if self._ui_mode == UIMode.ERROR:
            return "error"
        if self._device_control.is_muted():
            return "muted"
        return "idle"

    def _state_from_sprite(self, sprite: str | None) -> str | None:
        if not sprite:
            return None
        s = str(sprite).lower()
        stem = s.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        for state in _ASCII_STATES:
            if state in stem:
                return state
        aliases = {
            "listen": "listening",
            "speak": "playing",
            "ready": "response_cached",
            "mute": "muted",
            "safe": "safe_mode",
            "task": "task_running",
            "upload": "uploading",
            "block": "blocked",
            "offline": "offline",
            "error": "error",
            "think": "thinking",
            "idle": "idle",
            "confirm": "confirm",
        }
        for key, value in aliases.items():
            if key in stem:
                return value
        return None

    def _ascii_frames(self, state: str, size: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if size == "small":
            return _ASCII_FRAMES_SMALL.get(state, _ASCII_FRAMES_SMALL["idle"])
        return _ASCII_FRAMES_BIG.get(state, _ASCII_FRAMES_BIG["idle"])

    def _draw_character(self) -> None:
        """Draw character state if available."""
        if not self._character_sprite:
            return

        from oi_client.renderer import RenderColors

        # Draw a small character preview box
        box_x, box_y, box_w, box_h = self.renderer.character_box_rect()
        self.renderer._rect(box_x, box_y, box_w, box_h, RenderColors.card_bg)

        # Draw pulsing dot animation for idle state
        if self._character_animation and self._character_animation in ("idle", "breathe", "pulse"):
            frame = int(time.time() * 3) % 3
            dot_x = box_x + box_w - 24 + (frame * 3)
            dot_y = box_y + box_h // 2 - 3
            self.renderer._rect(dot_x, dot_y, 6, 6, RenderColors.online)

        # Prefer label, fallback to sprite id so the box is never blank.
        raw = (self._character_label or self._character_sprite or "").strip()
        if not raw:
            return
        label_text = raw[:22] + ("…" if len(raw) > 22 else "")
        tex, w, h = self.renderer._text(self.renderer._font_hint, label_text, RenderColors.accent)
        if tex:
            self.renderer._draw_tex(tex, box_x + 6, box_y + 4, w, h)
            self.renderer._destroy_tex(tex)

    def _hint_for_mode(self) -> str:
        if self._ui_mode == UIMode.CARD:
            has_audio = bool(self._response_audio)
            if has_audio:
                return "A=Replay  B=Back  Up/Down=Scroll"
            return "B=Back  Up/Down=Scroll"
        elif self._ui_mode in (UIMode.HOME, UIMode.READY):
            if self._device_control.is_muted():
                return "Muted  Start=Menu  Select=Settings"
            return "Up/Down=Select  A=Send  Hold X=Talk  Start=Menu  Select=Settings"
        elif self._ui_mode == UIMode.MENU:
            return "Up/Down=Select  A=Confirm  B=Cancel"
        elif self._ui_mode in (UIMode.ERROR, UIMode.OFFLINE):
            return "A=Retry  B=Quit"
        elif self._ui_mode == UIMode.WAITING or self._ui_mode == UIMode.RECORDING:
            return "B=Cancel"
        return "A=Select  B=Back  Start=Menu"

    def width_center(self, text_width: int) -> int:
        return self.renderer.center_x(text_width)

    def _max_card_scroll(self, title: str, body_text: str) -> int:
        """Compute max vertical scroll for current card content."""
        body_lines = body_text.split("\n") if body_text else []
        card_w = self.renderer.width - 20
        card_h = self.renderer.height - 90
        visible_h = max(0, card_h - (self.renderer.line_height() + self.renderer._scaled_px(28)))

        total_lines = 0
        for line in body_lines:
            if not line.strip():
                total_lines += 1
                continue
            wrapped = self.renderer._wrap_text(line, self.renderer._font_body, card_w - 20)
            total_lines += max(1, len(wrapped))

        content_h = total_lines * self.renderer.line_height()
        return max(0, content_h - visible_h)

    # ------------------------------------------------------------------
    # Recording control
    # ------------------------------------------------------------------

    async def start_recording(self) -> bool:
        """Promote active capture into a published voice stream."""
        if self._device_control.is_muted():
            self._card.title = "Muted"
            self._card.body = f"Muted until {self._device_control.muted_until}"
            self._ui_mode = UIMode.CARD
            return False
        if not self.datp or not self.datp.is_connected:
            return False
        if not self.audio.is_recording:
            if not self.audio.recording_init():
                self._card.title = "Recording"
                self._card.body = "No audio input device found"
                self._ui_mode = UIMode.ERROR
                return False
            if not self.audio.start_recording():
                return False

        self._ui_mode = UIMode.RECORDING
        self._recording_start_time = time.time()
        self._record_tx_stream_id = f"rec_{int(self._recording_start_time * 1000)}"
        self._record_tx_seq = 0

        # Immediately flush any speculative pre-recorded audio so early speech
        # (spoken before long-press threshold) is preserved.
        pending = self.audio.read_recording()
        if pending and self.datp and self.datp.is_connected:
            await self.datp.send_audio_chunk(self._record_tx_stream_id, self._record_tx_seq, pending, 16000)
            self._record_tx_seq += 1

        self._x_pre_recording = False
        self._card.title = "Recording"
        self._card.body = "Listening… hold X to talk"
        return True

    async def stop_recording(self) -> None:
        """Stop voice recording and send final event."""
        if not self.audio.is_recording:
            return
        duration_ms = int((time.time() - self._recording_start_time) * 1000)

        # Drain any queued audio before closing capture device.
        pending = self.audio.read_recording()
        self.audio.stop_recording()

        stream_id = self._record_tx_stream_id or f"rec_{int(self._recording_start_time * 1000)}"
        if pending and self.datp and self.datp.is_connected:
            await self.datp.send_audio_chunk(stream_id, self._record_tx_seq, pending, 16000)
            self._record_tx_seq += 1

        if self.datp and self.datp.is_connected:
            await self.datp.send_recording_finished(stream_id, duration_ms)

        self._record_tx_stream_id = None
        self._record_tx_seq = 0
        self._x_pre_recording = False
        self._ui_mode = UIMode.WAITING if self._online else UIMode.OFFLINE

    async def _reload_process(self) -> None:
        """Reload the app process so newly deployed files are picked up."""
        import sys
        await self.shutdown()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _is_recording_button(self, name: str, action: str) -> bool:
        """Check if this is a recording trigger (button X long-press)."""
        return name == "x" and action in ("long_press", "long_release")
