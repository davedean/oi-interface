"""Sketch of a generic Linux SBC handheld runtime for Oi.

This is illustrative only and shows the intended architecture.
The real implementation should import/adapt code from `src/oi-clients/oi-sim/` rather
than writing DATP from scratch.

Design note:
- This is a foreground app, not a service. User launches it from
  EmulationStation Ports menu, interacts, and quits back to ES.
- The DATP client/session layer wraps OiSim from oi-sim.
- SDL2 is used for input, rendering, and (optionally) audio.
- All external deps are vendored in `lib/`.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# In the real implementation, these imports come from the vendored oi-sim code.
# from sim.sim import OiSim
# from sim.state import State, StateMachine


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

DEFAULT_GATEWAY = "ws://localhost:8788/datp"
DEFAULT_DEVICE_ID = "sbc-handheld-001"


# ------------------------------------------------------------------
# Adapters
# ------------------------------------------------------------------

@dataclass
class InputEvent:
    type: str  # "button"
    name: str  # "a", "b", "up", "down", "menu", ...
    action: str  # "pressed", "released"


class InputAdapter:
    """SDL2 gamepad/joystick input adapter.

    Responsibilities:
    - Open the default SDL2 joystick
    - Poll for button presses/releases
    - Map raw SDL2 button codes to logical names
    - Emit normalized InputEvent objects

    In a real implementation this uses pysdl2.events / joystick modules.
    """

    def __init__(self) -> None:
        pass

    def poll(self) -> list[InputEvent]:
        """Return normalized logical input events since last poll."""
        # Real implementation would call SDL_PollEvent, filter for
        # SDL_JOYBUTTONDOWN / SDL_JOYBUTTONUP, map to logical names.
        return []


class Renderer:
    """SDL2 fullscreen renderer.

    Responsibilities:
    - Open a KMS/DRM fullscreen SDL2 window
    - Draw status screens, text cards, and button hints
    - Report effective text grid for capability hints

    In a real implementation this uses sdl2.ext.Window + sdl2.ext.Renderer\    or direct SDL_Renderer with TTF text.

    Display: 480x320 on RG351P. At ~12px font, roughly 40 cols x 20 rows.
    """

    def __init__(self, width: int = 480, height: int = 320) -> None:
        self.width = width
        self.height = height

    def render(self, mode: str, card_title: str, card_body: str) -> None:
        """Draw the current screen state."""
        print(f"[{mode}] {card_title}: {card_body[:60]}...")

    def effective_text_grid(self) -> tuple[int, int]:
        """Return (cols, rows) for capability advertisement."""
        return (40, 20)


class AudioAdapter:
    """Playback adapter -- aplay or SDL2 audio.

    Responsibilities:
    - Accept WAV bytes or temp file path
    - Play audio via aplay subprocess or SDL2 audio device
    - Report whether playback is currently active
    """

    def detect(self) -> dict[str, bool]:
        return {"has_audio_input": False, "has_audio_output": True}

    def play(self, wav_path: str | Path) -> None:
        pass

    def stop(self) -> None:
        pass

    def is_playing(self) -> bool:
        return False


# ------------------------------------------------------------------
# Device Controller (wraps OiSim)
# ------------------------------------------------------------------

class HandheldDevice:
    """Device controller that wraps an OiSim DATP client.

    This is the bridge between the user's handheld UI and the DATP world.
    It reuses the protocol brain from oi-sim and injects SDL2 adapters.

    Lifecycle:
        HOME → CONNECTING → READY → ... → QUIT (returns to ES)
    """

    def __init__(
        self,
        gateway_url: str = DEFAULT_GATEWAY,
        device_id: str = DEFAULT_DEVICE_ID,
    ) -> None:
        self.gateway_url = gateway_url
        self.device_id = device_id

        self.input = InputAdapter()
        self.renderer = Renderer()
        self.audio = AudioAdapter()

        # These would be real OiSim instances in production:
        # self._datp = OiSim(
        #     gateway=gateway_url,
        #     device_id=device_id,
        #     device_type="sbc-handheld",
        #     capabilities=self._build_capabilities(),
        # )
        self._connected = False
        self._mode = "HOME"
        self._card_title = "Oi"
        self._card_body = "Press A to start"
        self._running = True

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    def _build_capabilities(self) -> dict[str, Any]:
        audio_status = self.audio.detect()
        cols, rows = self.renderer.effective_text_grid()
        caps: dict[str, Any] = {
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
            "has_audio_input": audio_status["has_audio_input"],
            "has_audio_output": audio_status["has_audio_output"],
            "supports_text_input": False,
            "supports_confirm_buttons": True,
            "supports_scrolling_cards": True,
            "supports_voice": audio_status["has_audio_input"],
            "max_spoken_duration_s": 120,
        }
        if audio_status["has_audio_input"]:
            caps["input"].append("hold_to_record")
        return caps

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def bootstrap(self) -> None:
        """Initialize SDL2, set up initial screen, attempt connection."""
        self._mode = "CONNECTING"
        self._card_body = f"Connecting to {self.gateway_url}..."
        self.renderer.render(self._mode, self._card_title, self._card_body)
        # Real implementation:
        # await self._datp.connect()
        # self._connected = True
        # self._mode = "READY"

    def quit(self) -> None:
        """Clean shutdown: disconnect, release SDL2 resources, signal to exit."""
        self._running = False
        self._connected = False
        # Real implementation:
        # await self._datp.disconnect()
        # SDL2 cleanup

    # ------------------------------------------------------------------
    # Command handlers (called when gateway sends a command)
    # ------------------------------------------------------------------

    def on_show_status(self, state: str, label: str | None = None) -> None:
        self._mode = state.upper()
        self._card_body = label or state

    def on_show_card(self, title: str, body: str) -> None:
        self._mode = "CARD"
        self._card_title = title
        self._card_body = body

    def on_audio_play(self, wav_path: str) -> None:
        self.audio.play(wav_path)

    # ------------------------------------------------------------------
    # Input handlers (called when user presses a button)
    # ------------------------------------------------------------------

    def on_button_a(self) -> None:
        if self._mode == "HOME":
            # Show canned prompts
            self._mode = "MENU"
            self._card_body = "Select prompt"
        elif self._mode == "MENU":
            # Send selected prompt as text.event
            # Real: await self._datp.send_text_prompt("What time is it?")
            self._mode = "WAITING"
            self._card_body = "Asking Oi..."
        elif self._mode == "CARD":
            # Replay audio if cached
            self.on_audio_play("/tmp/latest.wav")

    def on_button_b(self) -> None:
        if self._mode == "CARD":
            self._mode = "HOME"
            self._card_body = "Ready"
        elif self._mode == "MENU":
            self._mode = "HOME"
            self._card_body = "Ready"
        elif self.audio.is_playing():
            self.audio.stop()

    def on_button_menu(self) -> None:
        if self._mode == "MENU":
            self.quit()
        else:
            self._mode = "MENU"
            self._card_body = "A: select | B: back | MENU: quit"

    def on_dpad(self, direction: str) -> None:
        # Scroll card text, change menu selection, etc.
        pass

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def loop_once(self) -> None:
        for event in self.input.poll():
            if event.name == "a" and event.action == "pressed":
                self.on_button_a()
            elif event.name == "b" and event.action == "pressed":
                self.on_button_b()
            elif event.name == "menu" and event.action == "pressed":
                self.on_button_menu()

        # Real implementation:
        # commands = await self._datp.poll_commands()
        # for cmd in commands: handle_command(cmd)

        self.renderer.render(self._mode, self._card_title, self._card_body)

    def run(self) -> None:
        self.bootstrap()
        while self._running:
            self.loop_once()
            # Real: await asyncio.sleep(0.016)  # ~60fps


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def main() -> None:
    device = HandheldDevice(
        gateway_url="ws://localhost:8788/datp",
        device_id="rg351p-001",
    )
    device.run()


if __name__ == "__main__":
    main()
