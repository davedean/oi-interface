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

        # Canned prompt selection
        self._prompt_idx = 0

        # Audio cache buffer
        self._audio_buffer = bytearray()
        self._audio_stream_id: str | None = None

        # Menu
        self._menu_idx = 0
        self._menu_items = ["Quit", "Reconnect"]

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

        # Sleep for ~33ms (30fps)
        await asyncio.sleep(0.033)

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    async def _handle_input(self, ev: InputEvent) -> None:
        if ev.type == "quit":
            self._running = False
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
                # Send selected prompt
                prompt = CANNED_PROMPTS[self._prompt_idx]
                await self._send_prompt(prompt)
            elif ev.name == "b":
                pass  # no-op in home
            elif ev.name == "up":
                self._prompt_idx = (self._prompt_idx - 1) % len(CANNED_PROMPTS)
            elif ev.name == "down":
                self._prompt_idx = (self._prompt_idx + 1) % len(CANNED_PROMPTS)

        elif self._ui_mode == UIMode.CARD:
            if ev.name == "a":
                # Replay audio if available
                pass
            elif ev.name == "b":
                self._ui_mode = UIMode.HOME
                self._card_scroll = 0
            elif ev.name == "up":
                self._card_scroll = max(0, self._card_scroll - 20)
            elif ev.name == "down":
                self._card_scroll += 20

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
                    await self.datp.reconnect()
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
        await self.datp.send_text_prompt(text)

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

        elif op == "audio.cache.put_begin":
            self._audio_buffer = bytearray()
            self._audio_stream_id = args.get("stream_id", f"stream_{uuid.uuid4().hex[:8]}")

        elif op == "audio.cache.put_chunk":
            import base64
            chunk = base64.b64decode(args.get("data_b64", ""))
            self._audio_buffer.extend(chunk)

        elif op == "audio.cache.put_end":
            if self._audio_buffer:
                # Clean up old temp audio files before creating new one
                for f in glob.glob("/tmp/oi_audio_*.wav"):
                    try:
                        os.unlink(f)
                    except Exception:
                        pass
                wav = self.audio.save_wav(bytes(self._audio_buffer))
                self.audio.play(wav)
                self._audio_buffer = bytearray()

        elif op == "audio.play":
            response_id = args.get("response_id", "latest")
            pass  # Would play cached audio; not implemented in MVP

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

        # Title bar with connection status
        title = "Oi — " + self._ui_mode.value.upper()
        self.renderer.draw_title(title, online=self._online)

        # Main content area based on mode
        if self._ui_mode == UIMode.CONNECTING:
            self.renderer.draw_card("Connecting", ["Attempting to reach oi-gateway..."], 0)
            self.renderer.draw_spinner(self.width_center(40), 180, self._spinner_frame)

        elif self._ui_mode == UIMode.READY or self._ui_mode == UIMode.HOME:
            lines = ["Select a prompt:"] + [f"  {'>' if i == self._prompt_idx else ' '} {p}" for i, p in enumerate(CANNED_PROMPTS)]
            self.renderer.draw_card("Home", lines, 0)

        elif self._ui_mode == UIMode.WAITING:
            self.renderer.draw_card("Waiting", ["Sending to gateway..."], 0)
            self.renderer.draw_spinner(self.width_center(40), 180, self._spinner_frame)

        elif self._ui_mode == UIMode.CARD:
            body_lines = self._card.body.split("\n")
            self.renderer.draw_card(self._card.title, body_lines, self._card_scroll)

        elif self._ui_mode == UIMode.MENU:
            lines = []
            for i, item in enumerate(self._menu_items):
                marker = "> " if i == self._menu_idx else "  "
                lines.append(f"{marker}{item}")
            self.renderer.draw_card("Menu", lines, 0)

        elif self._ui_mode == UIMode.ERROR:
            url = getattr(self, 'gateway_url', '?')
            body_lines = [
                self._card.body,
                "",
                f"URL: {url}",
                "",
                "A: Retry  B: Quit",
            ]
            self.renderer.draw_card("Error", body_lines, 0)

        elif self._ui_mode == UIMode.OFFLINE:
            url = getattr(self, 'gateway_url', '?')
            body_lines = [
                "Gateway unreachable.",
                "",
                f"URL: {url}",
                "",
                "A: Retry  B: Quit",
            ]
            self.renderer.draw_card("Offline", body_lines, 0)

        # Bottom hints
        hints = self._hint_for_mode()
        self.renderer.draw_hints(hints)

        self.renderer.present()

    def _hint_for_mode(self) -> str:
        if self._ui_mode == UIMode.CARD:
            return "A=Replay  B=Back  Up/Down=Scroll"
        elif self._ui_mode == UIMode.HOME:
            return "Up/Down=Select  A=Send  Start=Menu"
        elif self._ui_mode == UIMode.MENU:
            return "Up/Down=Select  A=Confirm  B=Cancel"
        elif self._ui_mode in (UIMode.ERROR, UIMode.OFFLINE):
            return "A=Retry  B=Quit"
        elif self._ui_mode == UIMode.WAITING:
            return "B=Cancel"
        return "A=Select  B=Back  Start=Menu"

    def width_center(self, text_width: int) -> int:
        return (480 - text_width) // 2
