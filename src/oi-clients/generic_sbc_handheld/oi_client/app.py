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
from dataclasses import dataclass
from enum import Enum
import uuid

from oi_client.state import State
from oi_client.input import Sdl2Input, InputEvent
from oi_client.renderer import Sdl2Renderer
from oi_client.audio import HandheldAudio
from oi_client.capabilities import build_capabilities
from oi_client.datp import DatpClient
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
]


@dataclass
class CardData:
    title: str = ""
    body: str = ""


logger = logging.getLogger(__name__)


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class HandheldApp:
    def __init__(self, gateway_url: str, device_id: str, device_type: str) -> None:
        self.gateway_url = gateway_url
        self.device_id = device_id
        self.device_type = device_type

        self.input = Sdl2Input()
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
        self._menu_items = ["Reload", "Reconnect", "Quit"]

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

        # Device command / telemetry state
        self._device_control = DeviceController()
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
        )
        connected = await self.datp.connect()
        if connected:
            self._online = True
            self._ui_mode = UIMode.READY
            self._card.body = "Select a prompt"
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
                    await self._handle_command(cmd)
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
                prompt = CANNED_PROMPTS[self._prompt_idx]
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

        if self._ui_mode == UIMode.MENU:
            await self._handle_menu(ev.name)
            return

        if ev.name == "start":
            self._ui_mode = UIMode.MENU
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
                    self._online = ok
                    self._ui_mode = UIMode.READY if ok else UIMode.ERROR
            elif ev.name == "b":
                logger.warning("Exiting due to B in %s mode", self._ui_mode)
                self._running = False

    async def _handle_menu(self, name: str) -> None:
        if name == "a":
            item = self._menu_items[self._menu_idx]
            if item == "Reload":
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
                    self._online = self.datp.is_connected
                    self._ui_mode = UIMode.READY if self._online else UIMode.ERROR
        elif name == "b":
            self._ui_mode = UIMode.HOME
        elif name == "up":
            self._menu_idx = (self._menu_idx - 1) % len(self._menu_items)
        elif name == "down":
            self._menu_idx = (self._menu_idx + 1) % len(self._menu_items)

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
        self._card = CardData(title="Oi", body="")
        self._ui_mode = UIMode.WAITING
        # Optimistic local character update so UI reflects waiting immediately.
        self._character_label = "Waiting"
        self._character_animation = "pulse"
        try:
            await self.datp.send_text_prompt(text)
        except Exception as exc:
            self._ui_mode = UIMode.ERROR
            self._card.title = "Send failed"
            self._card.body = str(exc)

    # ------------------------------------------------------------------
    # Command handling (from gateway)
    # ------------------------------------------------------------------

    async def _handle_command(self, cmd: dict) -> None:
        op = cmd.get("op", "")
        args = cmd.get("args", {})
        command_id = cmd.get("command_id", "")
        handler = self._command_handlers.get(op)
        ok = False
        if handler is None:
            logger.warning("Unhandled gateway command: %s", op)
        else:
            ok = bool(handler(op, args))
        if self.datp and command_id:
            await self.datp.ack_command(command_id, ok, op=op, args=args)

    def _handle_display_show_status(self, _op: str, args: dict) -> bool:
        state = args.get("state", "")
        label = args.get("label", "")
        self._ui_mode = self._state_to_ui(state)
        self._card.title = state.capitalize() if state else "Oi"
        if label:
            self._card.body = label
        return True

    def _handle_display_show_card(self, _op: str, args: dict) -> bool:
        self._card.title = args.get("title", "Response")
        self._card.body = args.get("body", "")
        self._card_scroll = 0
        self._ui_mode = UIMode.CARD
        return True

    def _handle_display_show_progress(self, _op: str, args: dict) -> bool:
        text = (args.get("text", "") or "").strip()
        if text and self._ui_mode == UIMode.WAITING:
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
            self.renderer.draw_card("Connecting", ["Attempting to reach oi-gateway..."], 0, ascii_bg_lines=blob)
            self.renderer.draw_spinner(self.width_center(40), 180, self._spinner_frame)

        elif self._ui_mode == UIMode.READY or self._ui_mode == UIMode.HOME:
            if self._device_control.is_muted():
                lines = [f"Muted until {self._device_control.muted_until or 'unknown'}", "", "Gateway commands still sync."]
                self.renderer.draw_card("Muted", lines, 0, ascii_bg_lines=blob)
            else:
                lines = ["Select a prompt:"] + [f"  {'>' if i == self._prompt_idx else ' '} {p}" for i, p in enumerate(CANNED_PROMPTS)]
                self.renderer.draw_card("Home", lines, 0, ascii_bg_lines=blob)

        elif self._ui_mode == UIMode.WAITING:
            # While waiting, show live progress and keep newest entries on screen.
            waiting_lines = ["Sending to gateway..."]
            if self._card.body:
                body_lines = [ln for ln in self._card.body.split("\n") if ln.strip()]
                if body_lines:
                    waiting_lines = body_lines
            progress_body = "\n".join(waiting_lines)
            self._progress_scroll = self._max_card_scroll("Waiting", progress_body)
            self.renderer.draw_card("Waiting", waiting_lines, self._progress_scroll, ascii_bg_lines=blob)
            self.renderer.draw_spinner(self.width_center(40), 180, self._spinner_frame)

        elif self._ui_mode == UIMode.CARD:
            body_lines = self._card.body.split("\n")
            self.renderer.draw_card(self._card.title, body_lines, self._card_scroll, ascii_bg_lines=blob)

        elif self._ui_mode == UIMode.MENU:
            lines = []
            for i, item in enumerate(self._menu_items):
                marker = "> " if i == self._menu_idx else "  "
                lines.append(f"{marker}{item}")
            self.renderer.draw_card("Menu", lines, 0, ascii_bg_lines=blob)

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
        """Return a Kirby-inspired animated ASCII character for current UI mode."""
        import time

        t = time.time()

        # HOME/READY: mostly still, occasional blink.
        home_blink = int(t * 1.1) % 10 == 0

        # WAITING: subtle left/right shuffle.
        wait_step = int(t * 3.0) % 2

        # SPEAKING (shown while response card is active): mouth movement cycle.
        speak_step = int(t * 6.0) % 4

        if self._ui_mode in (UIMode.WAITING, UIMode.RECORDING):
            feet = "    _/ /  \\ \\_" if wait_step == 0 else "   _/ /  \\ \\_ "
            return [
                "   .-\"\"\"\"\"\"-.   ",
                " .'  _    _  '. ",
                " /   (o)  (o)   \\",
                "|       ▿        |",
                "|    \\______/    |",
                " \\  .-.__.__-.  /",
                "  '._  ____  _.' ",
                feet,
            ]

        if self._ui_mode == UIMode.CARD:
            mouth = ["\\____/", "\\_oo_/", "\\_OO_/", "\\_oo_/"][speak_step]
            return [
                "   .-\"\"\"\"\"\"-.   ",
                " .'  _    _  '. ",
                " /   (o)  (o)   \\",
                "|       ▿        |",
                f"|    {mouth}      |",
                " \\  .-.__.__-.  /",
                "  '._  ____  _.' ",
                "     /_/  \\_\\    ",
            ]

        # HOME / READY / CONNECTING / ERROR / OFFLINE fallback.
        eyes = "(-)  (-)" if home_blink else "(o)  (o)"
        mouth = "\\______/"
        if self._ui_mode in (UIMode.ERROR, UIMode.OFFLINE):
            mouth = "\\_~~~~_/"

        return [
            "   .-\"\"\"\"\"\"-.   ",
            " .'  _    _  '. ",
            f" /   {eyes}   \\",
            "|       ▿        |",
            f"|    {mouth}    |",
            " \\  .-.__.__-.  /",
            "  '._  ____  _.' ",
            "     /_/  \\_\\    ",
        ]

    def _draw_character(self) -> None:
        """Draw character state if available."""
        if not self._character_sprite:
            return

        from oi_client.renderer import RenderColors

        # Draw a small character preview box
        box_x, box_y = 10, 34
        box_w, box_h = 160, 26
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
                return "Muted  Start=Menu"
            return "Up/Down=Select  A=Send  Hold X=Talk  Start=Menu"
        elif self._ui_mode == UIMode.MENU:
            return "Up/Down=Select  A=Confirm  B=Cancel"
        elif self._ui_mode in (UIMode.ERROR, UIMode.OFFLINE):
            return "A=Retry  B=Quit"
        elif self._ui_mode == UIMode.WAITING or self._ui_mode == UIMode.RECORDING:
            return "B=Cancel"
        return "A=Select  B=Back  Start=Menu"

    def width_center(self, text_width: int) -> int:
        return (480 - text_width) // 2

    def _max_card_scroll(self, title: str, body_text: str) -> int:
        """Compute max vertical scroll for current card content."""
        body_lines = body_text.split("\n") if body_text else []
        card_w = self.renderer.width - 20
        card_h = self.renderer.height - 90
        visible_h = max(0, card_h - 46)  # matches renderer body viewport

        total_lines = 0
        for line in body_lines:
            if not line.strip():
                total_lines += 1
                continue
            wrapped = self.renderer._wrap_text(line, self.renderer._font_body, card_w - 20)
            total_lines += max(1, len(wrapped))

        content_h = total_lines * 18
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
