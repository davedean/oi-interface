#!/usr/bin/env python3
"""Main Oi handheld app loop.

Ties together SDL2 input, renderer, audio, and DATP client.
"""

from __future__ import annotations

import asyncio
import glob
import os
from dataclasses import dataclass
from enum import Enum
import uuid

from oi_client.state import State
from oi_client.input import Sdl2Input, InputEvent
from oi_client.renderer import Sdl2Renderer
from oi_client.audio import HandheldAudio
from oi_client.datp import DatpClient
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
        self._recording_start_time: float = 0.0

        # Per-response audio tracking: maps response_id -> wav_path
        self._response_audio: dict[str, str] = {}

        # Menu
        self._menu_idx = 0
        self._menu_items = ["Quit", "Reconnect"]

        # Character display state (default to IDLE placeholder)
        self._character_sprite: str | None = "idle"
        self._character_label: str = "Waiting..."
        self._character_animation: str | None = "idle"
        self._character_overlay_sprite: str | None = None
        self._character_overlay_label: str = ""
        self._character_pack_id: str = ""

        # Display version
        self._version = self._get_version()

    def _get_version(self) -> str:
        """Get git commit hash for display."""
        import subprocess
        import os
        
        # Try multiple possible locations
        possible_paths = [
            "/home/dev/oi-interface",
            "/home/dev/oi-interface/src/oi-firmware",
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
        caps = {
            "input": ["buttons", "dpad", "confirm_buttons"],
            "output": ["screen", "cached_audio"],
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
            ],
            "display_width": cols,
            "display_height": rows,
            "has_audio_input": audio_status.has_input,
            "has_audio_output": audio_status.has_output,
            "supports_text_input": False,
            "supports_confirm_buttons": True,
            "supports_scrolling_cards": True,
            "supports_voice": audio_status.has_input,
            "max_spoken_duration_s": 120,
        }
        if audio_status.has_input:
            caps["input"].append("hold_to_record")
        return caps

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        # Process input
        for event in self.input.poll():
            await self._handle_input(event)

        # Process DATP commands
        if self.datp:
            for cmd in self.datp.get_commands():
                self._handle_command(cmd)
            # Check connection status
            if not self.datp.is_connected and self._online:
                self._online = False
                self._ui_mode = UIMode.OFFLINE

        # Draw
        self._draw_frame()
        self._spinner_frame += 1

        # Stream recorded audio chunks if actively recording
        await self._stream_recorded_audio()

        # Sleep for ~33ms (30fps)
        await asyncio.sleep(0.033)

    async def _stream_recorded_audio(self) -> None:
        """Read any newly recorded PCM audio and stream it to gateway."""
        if not self.audio.is_recording:
            return
        chunk = self.audio.read_recording()
        if chunk and self.datp and self.datp.is_connected and self._ui_mode == UIMode.RECORDING:
            stream_id = f"rec_{int(self._recording_start_time * 1000)}"
            # We don't track seq here since chunking is coarse
            await self.datp.send_audio_chunk(stream_id, 0, chunk, 16000)
            self._card.title = "Recording"
            self._card.body = f"Streaming audio… {len(chunk)} bytes"

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    async def _handle_input(self, ev: InputEvent) -> None:
        if ev.type == "quit":
            self._running = False
            return

        # Handle long-press recording controls before generic pressed gating.
        if ev.name == "a" and ev.action == "long_press" and self._ui_mode in (UIMode.HOME, UIMode.READY):
            await self.start_recording()
            return
        if ev.name == "a" and ev.action == "long_release" and self.audio.is_recording:
            await self.stop_recording()
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
            if ev.name == "a":
                if ev.action == "long_press":
                    # Start recording on long press of A
                    await self.start_recording()
                elif ev.action == "pressed":
                    # Short press: send selected prompt (only if not recording)
                    if self._ui_mode != UIMode.RECORDING:
                        prompt = CANNED_PROMPTS[self._prompt_idx]
                        await self._send_prompt(prompt)
                elif ev.action == "long_release":
                    # Stop recording on release after long press
                    await self.stop_recording()
            elif ev.name == "b":
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
                self._running = False

    async def _handle_menu(self, name: str) -> None:
        if name == "a":
            item = self._menu_items[self._menu_idx]
            if item == "Quit":
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

    def _handle_command(self, cmd: dict) -> None:
        op = cmd.get("op", "")
        args = cmd.get("args", {})

        if op == "display.show_status":
            state = args.get("state", "")
            label = args.get("label", "")
            self._ui_mode = self._state_to_ui(state)
            self._card.title = state.capitalize() if state else "Oi"
            if label:
                self._card.body = label

        elif op == "display.show_card":
            self._card.title = args.get("title", "Response")
            self._card.body = args.get("body", "")
            self._card_scroll = 0
            self._ui_mode = UIMode.CARD

        elif op == "display.show_progress":
            text = (args.get("text", "") or "").strip()
            if text:
                if self._ui_mode == UIMode.WAITING:
                    self._card.title = "Working"
                    body = self._card.body or ""
                    self._card.body = (body + ("\n" if body else "") + f"• {text}")[-1200:]
                    self._progress_scroll = self._max_card_scroll("Waiting", self._card.body)

        elif op == "display.show_response_delta":
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

        elif op == "character.set_state":
            self._character_sprite = args.get("sprite")
            self._character_label = args.get("label", "")
            self._character_animation = args.get("animation")
            self._character_overlay_sprite = args.get("overlay")
            self._character_overlay_label = args.get("overlay_label", "")
            self._character_pack_id = args.get("pack_id", "")

        elif op == "audio.cache.put_begin":
            self._recording_stream_id = args.get("stream_id", f"stream_{uuid.uuid4().hex[:8]}")
            self._recording_chunks = []

        elif op == "audio.cache.put_chunk":
            import base64
            chunk = base64.b64decode(args.get("data_b64", ""))
            if chunk:
                self._recording_chunks.append(chunk)

        elif op == "audio.cache.put_end":
            if self._recording_chunks:
                combined = b''.join(self._recording_chunks)
                wav = self.audio.save_wav(combined)
                response_id = args.get("response_id", "latest")
                self._response_audio[response_id] = str(wav)
                self.audio.play(str(wav))
                self._recording_chunks = []

        elif op == "audio.play":
            response_id = args.get("response_id", "latest")
            wav_path = self._response_audio.get(response_id)
            if wav_path and os.path.exists(wav_path):
                self.audio.play(wav_path)
            elif response_id == "latest" and self._response_audio:
                last_wav = list(self._response_audio.values())[-1]
                if os.path.exists(last_wav):
                    self.audio.play(last_wav)

        elif op == "audio.stop":
            self.audio.stop()

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
        """Return an animated ASCII blob based on current UI mode/state."""
        import time
        blink = int(time.time() * 1.2) % 8 == 0
        step = int(time.time() * 3) % 2

        eye = "- -" if blink else "o o"
        mouth = "_" if self._ui_mode in (UIMode.READY, UIMode.HOME, UIMode.CARD) else "o"
        if self._ui_mode in (UIMode.ERROR, UIMode.OFFLINE):
            mouth = "~"
        if self._ui_mode == UIMode.WAITING:
            mouth = "."

        arm_l = "<" if step == 0 else "("
        arm_r = ">" if step == 0 else ")"

        return [
            "   .-''''-.   ",
            f"  /  {eye}  \\  ",
            f" |    {mouth}    | ",
            f"  \\  ____  /  ",
            f"   {arm_l}____{arm_r}   ",
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
        elif self._ui_mode == UIMode.HOME:
            return "Up/Down=Select  A=Send  Start=Menu"
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
        """Start voice recording and streaming to gateway."""
        if not self.datp or not self.datp.is_connected:
            return False
        if self.audio.is_recording:
            return True
        if not self.audio.recording_init():
            return False
        ok = self.audio.start_recording()
        if ok:
            self._ui_mode = UIMode.RECORDING
            self._recording_start_time = time.time()
        return ok

    async def stop_recording(self) -> None:
        """Stop voice recording and send final event."""
        if not self.audio.is_recording:
            return
        duration_ms = int((time.time() - self._recording_start_time) * 1000)
        self.audio.stop_recording()
        # Send any remaining chunks
        chunk = self.audio.read_recording()
        if chunk and self.datp and self.datp.is_connected:
            stream_id = f"rec_{int(self._recording_start_time * 1000)}"
            await self.datp.send_audio_chunk(stream_id, 0, chunk, 16000)
            await self.datp.send_recording_finished(stream_id, duration_ms)
        self._ui_mode = UIMode.READY if self._online else UIMode.OFFLINE

    def _is_recording_button(self, name: str, action: str) -> bool:
        """Check if this is a recording trigger (button A long-press)."""
        return name == "a" and action in ("long_press", "long_release")
