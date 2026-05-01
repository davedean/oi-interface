from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest

client_src = Path(__file__).parent.parent / "generic_sbc_handheld"
if str(client_src) not in sys.path:
    sys.path.insert(0, str(client_src))

import oi_client.button_mapping as mapping_mod
from oi_client.button_mapping import (
    DEBOUNCE_SECONDS,
    RESTART_HOLD_SECONDS,
    SHORTCUT_IDLE_WINDOW_SECONDS,
    _advance_release_guard,
    _find_collision,
    _is_duplicate_press,
    _mapping_signature,
    _resolve_mapping_event,
    _update_restart_hold,
    check_manual_mapping_shortcut,
)
from oi_client.input import RawInputEvent


class StubRenderer:
    def clear(self):
        return None

    def draw_title(self, *args, **kwargs):
        return None

    def draw_card(self, *args, **kwargs):
        return None

    def draw_hints(self, *args, **kwargs):
        return None

    def present(self):
        return None


class StubShortcutInput:
    def __init__(self, batches):
        self._batches = list(batches)

    def poll_raw(self):
        return self._batches.pop(0) if self._batches else []

    def controller_name(self):
        return "stub-controller"


def test_resolve_mapping_event_handles_button_hat_and_release() -> None:
    assert _resolve_mapping_event(RawInputEvent("button", "pressed", 4)) == {"type": "button", "value": 4}
    assert _resolve_mapping_event(RawInputEvent("hat", "pressed", 8, hat=1)) == {"type": "hat", "hat": 1, "value": 8}
    assert _resolve_mapping_event(RawInputEvent("hat", "released", 0, hat=1)) is None
    assert _resolve_mapping_event(RawInputEvent("button", "released", 4)) is None


def test_update_restart_hold_requires_two_buttons_held_long_enough() -> None:
    held: set[int] = set()

    started, restart = _update_restart_hold(held, None, RawInputEvent("button", "pressed", 1), 10.0)
    assert started is None
    assert restart is False

    started, restart = _update_restart_hold(held, started, RawInputEvent("button", "pressed", 2), 10.5)
    assert started == 10.5
    assert restart is False

    started, restart = _update_restart_hold(held, started, RawInputEvent("button", "pressed", 2), 10.5 + RESTART_HOLD_SECONDS)
    assert started is None
    assert restart is True


def test_update_restart_hold_clears_when_buttons_released() -> None:
    held = {1, 2}

    started, restart = _update_restart_hold(held, 5.0, RawInputEvent("button", "released", 2), 5.5)

    assert started is None
    assert restart is False
    assert held == {1}


def test_mapping_signature_and_collision_detection() -> None:
    mapping = {
        "a": {"type": "button", "value": 4},
        "up": {"type": "hat", "hat": 0, "value": 1},
    }

    assert _mapping_signature(mapping["a"]) == ("button", 4, 0)
    assert _mapping_signature(mapping["up"]) == ("hat", 0, 1)
    assert _find_collision(mapping, "b", {"type": "button", "value": 4}) == "a"
    assert _find_collision(mapping, "right", {"type": "hat", "hat": 0, "value": 1}) == "up"
    assert _find_collision(mapping, "a", {"type": "button", "value": 4}) is None


def test_advance_release_guard_waits_for_matching_release() -> None:
    guard = ("button", 7, 0)
    assert _advance_release_guard(guard, RawInputEvent("button", "pressed", 7)) == guard
    assert _advance_release_guard(guard, RawInputEvent("button", "released", 7)) is None

    hat_guard = ("hat", 0, 4)
    assert _advance_release_guard(hat_guard, RawInputEvent("hat", "pressed", 4, hat=0)) == hat_guard
    assert _advance_release_guard(hat_guard, RawInputEvent("hat", "released", 0, hat=0)) is None


def test_duplicate_press_detection_uses_debounce_window() -> None:
    event = RawInputEvent("button", "pressed", 9)
    sig = ("button", 9, 0)

    assert _is_duplicate_press(event, sig, 10.0, 10.0 + (DEBOUNCE_SECONDS / 2)) is True
    assert _is_duplicate_press(event, sig, 10.0, 10.0 + DEBOUNCE_SECONDS + 0.01) is False
    assert _is_duplicate_press(RawInputEvent("button", "released", 9), sig, 10.0, 10.1) is False


@pytest.mark.asyncio
async def test_manual_mapping_shortcut_triggers_after_two_button_hold(monkeypatch) -> None:
    renderer = StubRenderer()
    input_device = StubShortcutInput([
        [RawInputEvent("button", "pressed", 1), RawInputEvent("button", "pressed", 2)],
        [RawInputEvent("button", "pressed", 2)],
    ])
    times = iter([0.0, 0.0, 0.0, 0.0, 3.2, 3.2])
    monkeypatch.setattr(mapping_mod.time, "time", lambda: next(times))

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(mapping_mod.asyncio, "sleep", fake_sleep)

    assert await check_manual_mapping_shortcut(renderer, input_device) is True


@pytest.mark.asyncio
async def test_manual_mapping_shortcut_exits_after_idle_window(monkeypatch) -> None:
    renderer = StubRenderer()
    input_device = StubShortcutInput([[], []])
    times = iter([0.0, 0.0, SHORTCUT_IDLE_WINDOW_SECONDS + 0.01])
    monkeypatch.setattr(mapping_mod.time, "time", lambda: next(times))

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(mapping_mod.asyncio, "sleep", fake_sleep)

    assert await check_manual_mapping_shortcut(renderer, input_device) is False
