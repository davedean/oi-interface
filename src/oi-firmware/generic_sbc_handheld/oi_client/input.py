#!/usr/bin/env python3
"""SDL2 gamepad input adapter for Linux handhelds.

Maps raw SDL2 joystick events to logical button names using a per-device
button map.  Verified map for RG351P is baked in.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import Any

os.environ.setdefault("PYSDL2_DLL_PATH", "/usr/lib")

import sdl2
from sdl2 import (
    SDL_INIT_JOYSTICK, SDL_INIT_EVENTS,
    SDL_JOYBUTTONDOWN, SDL_JOYBUTTONUP, SDL_JOYHATMOTION,
    SDL_KEYDOWN,
    SDLK_UP, SDLK_DOWN, SDLK_LEFT, SDLK_RIGHT,
    SDLK_RETURN, SDLK_BACKSPACE,
    SDLK_q, SDLK_ESCAPE,
    SDL_Event, SDL_PollEvent,
    SDL_NumJoysticks, SDL_IsGameController,
    SDL_GameControllerOpen, SDL_GameControllerClose,
    SDL_JoystickOpen, SDL_JoystickClose,
    SDL_JoystickInstanceID,
)


@dataclass(frozen=True)
class InputEvent:
    type: str        # "button" | "axis" | "quit"
    name: str        # logical name
    action: str      # "pressed" | "released"
    raw: int = 0     # raw SDL value


# Verified RG351P mapping (AmberELEC, 2026-04-29)
RG351P_MAP: dict[str, dict[str, Any]] = {
    "a":      {"type": "button", "value": 0},
    "b":      {"type": "button", "value": 1},
    "x":      {"type": "button", "value": 2},
    "y":      {"type": "button", "value": 3},
    "l1":     {"type": "button", "value": 4},
    "r1":     {"type": "button", "value": 5},
    "start":  {"type": "button", "value": 6},
    "select": {"type": "button", "value": 7},
    "l3":     {"type": "button", "value": 8},
    "r3":     {"type": "button", "value": 9},
    "up":     {"type": "hat", "hat": 0, "value": 1},
    "down":   {"type": "hat", "hat": 0, "value": 4},
    "left":   {"type": "hat", "hat": 0, "value": 8},
    "right":  {"type": "hat", "hat": 0, "value": 2},
}

# Build reverse lookup: (event_type, raw_value) -> logical_name
# For hats: ("hat", hat_id, value) -> logical_name
# For buttons: ("button", btn_id) -> logical_name
_BUTTON_TO_NAME: dict[tuple[str, int], str] = {}
_HAT_TO_NAME: dict[tuple[str, int, int], str] = {}

for name, mapping in RG351P_MAP.items():
    if mapping["type"] == "button":
        _BUTTON_TO_NAME[("button", mapping["value"])] = name
    elif mapping["type"] == "hat":
        _HAT_TO_NAME[("hat", mapping["hat"], mapping["value"])] = name


class Sdl2Input:
    """Polls SDL2 events and returns logical InputEvents."""

    def __init__(self) -> None:
        self._controller = None
        self._joystick = None
        self._joystick_id = -1
        self._event = SDL_Event()

    def init(self) -> bool:
        if sdl2.SDL_Init(SDL_INIT_JOYSTICK | SDL_INIT_EVENTS) != 0:
            print(f"SDL_Init(joystick) failed")
            return False

        count = SDL_NumJoysticks()
        if count == 0:
            print("No joysticks found")
            return False

        for i in range(count):
            if SDL_IsGameController(i):
                self._controller = SDL_GameControllerOpen(i)
                name = sdl2.SDL_GameControllerName(self._controller)
                print(f"Gamepad: {name.decode() if name else '???'}")
                return True
            else:
                self._joystick = SDL_JoystickOpen(i)
                if self._joystick:
                    self._joystick_id = SDL_JoystickInstanceID(self._joystick)
                    print(f"Joystick: id={self._joystick_id}")
                    return True

        return False

    def shutdown(self) -> None:
        if self._controller:
            SDL_GameControllerClose(self._controller)
            self._controller = None
        if self._joystick:
            SDL_JoystickClose(self._joystick)
            self._joystick = None
        sdl2.SDL_QuitSubSystem(SDL_INIT_JOYSTICK | SDL_INIT_EVENTS)

    def poll(self) -> list[InputEvent]:
        """Poll SDL events and return a list of logical InputEvents."""
        events: list[InputEvent] = []
        while SDL_PollEvent(ctypes.byref(self._event)) != 0:
            ev = self._event
            et = ev.type

            if et == sdl2.SDL_QUIT:
                events.append(InputEvent("quit", "quit", "pressed"))

            elif et == SDL_KEYDOWN:
                key = ev.key.keysym.sym
                if key == SDLK_q or key == SDLK_ESCAPE:
                    events.append(InputEvent("button", "start", "pressed"))
                elif key == SDLK_RETURN:
                    events.append(InputEvent("button", "a", "pressed"))
                elif key == SDLK_BACKSPACE:
                    events.append(InputEvent("button", "b", "pressed"))
                elif key == SDLK_UP:
                    events.append(InputEvent("button", "up", "pressed"))
                elif key == SDLK_DOWN:
                    events.append(InputEvent("button", "down", "pressed"))
                elif key == SDLK_LEFT:
                    events.append(InputEvent("button", "left", "pressed"))
                elif key == SDLK_RIGHT:
                    events.append(InputEvent("button", "right", "pressed"))

            elif et == SDL_JOYBUTTONDOWN:
                btn = ev.jbutton.button
                name = _BUTTON_TO_NAME.get(("button", btn))
                if name:
                    events.append(InputEvent("button", name, "pressed", btn))
                else:
                    events.append(InputEvent("button", f"btn{btn}", "pressed", btn))

            elif et == SDL_JOYBUTTONUP:
                btn = ev.jbutton.button
                name = _BUTTON_TO_NAME.get(("button", btn))
                if name:
                    events.append(InputEvent("button", name, "released", btn))

            elif et == SDL_JOYHATMOTION:
                hat = ev.jhat.hat
                val = ev.jhat.value
                if val == 0:
                    # Hat returned to center — not generating an event
                    continue
                name = _HAT_TO_NAME.get(("hat", hat, val))
                if name:
                    events.append(InputEvent("button", name, "pressed", val))
                else:
                    events.append(InputEvent("hat", f"hat{hat}", "pressed", val))

        return events
