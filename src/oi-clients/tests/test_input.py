"""Tests for handheld input helpers."""
from __future__ import annotations

import sys
from pathlib import Path


client_src = Path(__file__).parent.parent / "generic_sbc_handheld"
if str(client_src) not in sys.path:
    sys.path.insert(0, str(client_src))

import oi_client.input as input_mod
from oi_client.input import InputEvent, Sdl2Input


def _make_poll(events):
    queue = list(events)

    def fake_poll(ptr):
        if not queue:
            return 0
        event = queue.pop(0)
        ptr._obj.type = event["type"]
        if "sym" in event:
            ptr._obj.key.keysym.sym = event["sym"]
        if "button" in event:
            ptr._obj.jbutton.button = event["button"]
        if "hat" in event:
            ptr._obj.jhat.hat = event["hat"]
            ptr._obj.jhat.value = event["value"]
        return 1

    return fake_poll


def test_check_hold_starts_tracking(monkeypatch) -> None:
    inp = Sdl2Input()
    monkeypatch.setattr(inp, "_get_frame_time", lambda: 12.5)

    events = inp._check_hold(2, "x")

    assert events == []
    assert inp._held_buttons[2] == (1, "x", 12.5)


def test_release_button_emits_long_release_only_for_long_press() -> None:
    inp = Sdl2Input()
    inp._held_buttons[2] = (inp._hold_threshold, "x", 0.0)

    events = inp._release_button(2)

    assert events == [InputEvent("button", "x", "long_release", 2)]
    assert 2 not in inp._held_buttons


def test_poll_emits_long_press_when_threshold_reached(monkeypatch) -> None:
    inp = Sdl2Input()
    inp._held_buttons[2] = (inp._hold_threshold - 1, "x", 0.0)
    monkeypatch.setattr(input_mod, "SDL_PollEvent", lambda _: 0)

    events = inp.poll()

    assert InputEvent("button", "x", "long_press", 2) in events
    assert inp._held_buttons[2][0] == inp._hold_threshold


def test_get_frame_time_uses_sdl_ticks(monkeypatch) -> None:
    monkeypatch.setattr(input_mod.sdl2, "SDL_GetTicks", lambda: 4321)
    inp = Sdl2Input()

    assert inp._get_frame_time() == 4.321


def test_init_returns_false_when_no_joysticks(monkeypatch) -> None:
    monkeypatch.setattr(input_mod.sdl2, "SDL_Init", lambda flags: 0)
    monkeypatch.setattr(input_mod, "SDL_NumJoysticks", lambda: 0)
    inp = Sdl2Input()

    assert inp.init() is False


def test_poll_maps_keyboard_and_button_events(monkeypatch) -> None:
    monkeypatch.setattr(
        input_mod,
        "SDL_PollEvent",
        _make_poll([
            {"type": input_mod.SDL_KEYDOWN, "sym": input_mod.SDLK_UP},
            {"type": input_mod.SDL_JOYBUTTONDOWN, "button": 2},
            {"type": input_mod.SDL_JOYBUTTONUP, "button": 2},
            {"type": input_mod.SDL_JOYHATMOTION, "hat": 0, "value": 1},
        ]),
    )
    inp = Sdl2Input()

    events = inp.poll()

    assert InputEvent("button", "up", "pressed") in events
    assert InputEvent("button", "x", "pressed", 2) in events
    assert InputEvent("button", "x", "released", 2) in events
    assert InputEvent("button", "up", "pressed", 1) in events
