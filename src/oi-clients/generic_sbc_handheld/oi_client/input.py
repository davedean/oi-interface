#!/usr/bin/env python3
"""SDL2 gamepad input adapter for Linux handhelds.

Maps raw SDL2 joystick events to logical button names using a per-device
button map. If no custom profile exists yet, callers can still access raw
button / hat events to run an on-device mapping wizard.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import Any

os.environ.setdefault("PYSDL2_DLL_PATH", "/usr/lib")

import sdl2
from sdl2 import (
    SDL_INIT_JOYSTICK,
    SDL_INIT_EVENTS,
    SDL_JOYBUTTONDOWN,
    SDL_JOYBUTTONUP,
    SDL_JOYHATMOTION,
    SDL_KEYDOWN,
    SDLK_UP,
    SDLK_DOWN,
    SDLK_LEFT,
    SDLK_RIGHT,
    SDLK_RETURN,
    SDLK_BACKSPACE,
    SDLK_q,
    SDLK_ESCAPE,
    SDL_Event,
    SDL_PollEvent,
    SDL_NumJoysticks,
    SDL_IsGameController,
    SDL_GameControllerOpen,
    SDL_GameControllerClose,
    SDL_JoystickOpen,
    SDL_JoystickClose,
    SDL_JoystickInstanceID,
)


@dataclass(frozen=True)
class InputEvent:
    type: str
    name: str
    action: str
    raw: int = 0


@dataclass(frozen=True)
class RawInputEvent:
    type: str
    action: str
    value: int
    hat: int = 0


RG351P_MAP: dict[str, dict[str, Any]] = {
    "a": {"type": "button", "value": 0},
    "b": {"type": "button", "value": 1},
    "x": {"type": "button", "value": 2},
    "y": {"type": "button", "value": 3},
    "l1": {"type": "button", "value": 4},
    "r1": {"type": "button", "value": 5},
    "start": {"type": "button", "value": 6},
    "select": {"type": "button", "value": 7},
    "l3": {"type": "button", "value": 8},
    "r3": {"type": "button", "value": 9},
    "l2": {"type": "button", "value": 10},
    "r2": {"type": "button", "value": 11},
    "up": {"type": "hat", "hat": 0, "value": 1},
    "down": {"type": "hat", "hat": 0, "value": 4},
    "left": {"type": "hat", "hat": 0, "value": 8},
    "right": {"type": "hat", "hat": 0, "value": 2},
}


def _normalize_button_map(mapping: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    source = mapping or RG351P_MAP
    normalized: dict[str, dict[str, Any]] = {}
    for name, spec in source.items():
        if not isinstance(spec, dict):
            continue
        kind = str(spec.get("type", "")).strip().lower()
        if kind == "button" and "value" in spec:
            normalized[name] = {"type": "button", "value": int(spec["value"])}
        elif kind == "hat" and "value" in spec:
            normalized[name] = {
                "type": "hat",
                "hat": int(spec.get("hat", 0)),
                "value": int(spec["value"]),
            }
    return normalized


class Sdl2Input:
    """Polls SDL2 events and returns logical InputEvents."""

    def __init__(self, button_map: dict[str, dict[str, Any]] | None = None) -> None:
        self._controller = None
        self._joystick = None
        self._joystick_id = -1
        self._event = SDL_Event()
        self._held_buttons: dict[int, tuple[int, str, float]] = {}
        self._hold_threshold = 8
        self._controller_name = "unknown"
        self._has_custom_mapping = button_map is not None
        self.set_button_map(button_map, custom=button_map is not None)

    def set_button_map(self, mapping: dict[str, dict[str, Any]] | None, *, custom: bool = True) -> None:
        self._button_map = _normalize_button_map(mapping)
        self._button_to_name: dict[tuple[str, int], str] = {}
        self._hat_to_name: dict[tuple[str, int, int], str] = {}
        for name, spec in self._button_map.items():
            if spec["type"] == "button":
                self._button_to_name[("button", int(spec["value"]))] = name
            elif spec["type"] == "hat":
                self._hat_to_name[("hat", int(spec.get("hat", 0)), int(spec["value"]))] = name
        self._has_custom_mapping = custom

    def export_button_map(self) -> dict[str, dict[str, Any]]:
        return {name: dict(spec) for name, spec in self._button_map.items()}

    def has_custom_mapping(self) -> bool:
        return self._has_custom_mapping

    def controller_name(self) -> str:
        return self._controller_name

    def _check_hold(self, btn_id: int, logical_name: str) -> list[InputEvent]:
        now = self._get_frame_time()
        if btn_id not in self._held_buttons:
            self._held_buttons[btn_id] = (1, logical_name, now)
        return []

    def _get_frame_time(self) -> float:
        return sdl2.SDL_GetTicks() / 1000.0

    def _release_button(self, btn_id: int) -> list[InputEvent]:
        events: list[InputEvent] = []
        if btn_id in self._held_buttons:
            count, name, _started = self._held_buttons[btn_id]
            if count >= self._hold_threshold:
                events.append(InputEvent("button", name, "long_release", btn_id))
            del self._held_buttons[btn_id]
        return events

    def init(self) -> bool:
        if sdl2.SDL_Init(SDL_INIT_JOYSTICK | SDL_INIT_EVENTS) != 0:
            print("SDL_Init(joystick) failed")
            return False

        count = SDL_NumJoysticks()
        if count == 0:
            print("No joysticks found")
            return False

        for i in range(count):
            if SDL_IsGameController(i):
                self._controller = SDL_GameControllerOpen(i)
                name = sdl2.SDL_GameControllerName(self._controller)
                self._controller_name = name.decode() if name else "unknown"
                print(f"Gamepad: {self._controller_name}")
                return True
            self._joystick = SDL_JoystickOpen(i)
            if self._joystick:
                self._joystick_id = SDL_JoystickInstanceID(self._joystick)
                self._controller_name = f"joystick-{self._joystick_id}"
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

    def poll_raw(self) -> list[RawInputEvent]:
        events: list[RawInputEvent] = []
        while SDL_PollEvent(ctypes.byref(self._event)) != 0:
            ev = self._event
            et = ev.type
            if et == sdl2.SDL_QUIT:
                events.append(RawInputEvent("quit", "pressed", 0))
            elif et == SDL_KEYDOWN:
                key = ev.key.keysym.sym
                if key in (SDLK_q, SDLK_ESCAPE):
                    events.append(RawInputEvent("quit", "pressed", int(key)))
                elif key in (SDLK_UP, SDLK_DOWN, SDLK_LEFT, SDLK_RIGHT):
                    events.append(RawInputEvent("key", "pressed", int(key)))
            elif et == SDL_JOYBUTTONDOWN:
                events.append(RawInputEvent("button", "pressed", int(ev.jbutton.button)))
            elif et == SDL_JOYBUTTONUP:
                events.append(RawInputEvent("button", "released", int(ev.jbutton.button)))
            elif et == SDL_JOYHATMOTION:
                value = int(ev.jhat.value)
                action = "released" if value == 0 else "pressed"
                events.append(RawInputEvent("hat", action, value, hat=int(ev.jhat.hat)))
        return events

    def poll(self) -> list[InputEvent]:
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
                btn = int(ev.jbutton.button)
                name = self._button_to_name.get(("button", btn), f"btn{btn}")
                events.append(InputEvent("button", name, "pressed", btn))
                events.extend(self._check_hold(btn, name))

            elif et == SDL_JOYBUTTONUP:
                btn = int(ev.jbutton.button)
                name = self._button_to_name.get(("button", btn), f"btn{btn}")
                events.extend(self._release_button(btn))
                events.append(InputEvent("button", name, "released", btn))

            elif et == SDL_JOYHATMOTION:
                hat = int(ev.jhat.hat)
                val = int(ev.jhat.value)
                if val == 0:
                    continue
                name = self._hat_to_name.get(("hat", hat, val))
                if name:
                    events.append(InputEvent("button", name, "pressed", val))
                else:
                    events.append(InputEvent("hat", f"hat{hat}", "pressed", val))

        for btn_id, (count, name, started) in list(self._held_buttons.items()):
            count += 1
            self._held_buttons[btn_id] = (count, name, started)
            if count == self._hold_threshold:
                events.append(InputEvent("button", name, "long_press", btn_id))

        return events
