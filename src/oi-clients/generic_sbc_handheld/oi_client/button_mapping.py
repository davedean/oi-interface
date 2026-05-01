from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from oi_client.input import RawInputEvent


RESTART_HOLD_SECONDS = 3.0
DEBOUNCE_SECONDS = 0.35
SHORTCUT_IDLE_WINDOW_SECONDS = 0.75
SHORTCUT_POLL_WINDOW_SECONDS = 3.5


@dataclass(frozen=True)
class ButtonMappingStep:
    logical_name: str
    prompt: str


BUTTON_MAPPING_STEPS: tuple[ButtonMappingStep, ...] = (
    ButtonMappingStep("a", "Press the RIGHT face button"),
    ButtonMappingStep("b", "Press the BOTTOM face button"),
    ButtonMappingStep("x", "Press the TOP face button"),
    ButtonMappingStep("y", "Press the LEFT face button"),
    ButtonMappingStep("up", "Press DPAD UP"),
    ButtonMappingStep("down", "Press DPAD DOWN"),
    ButtonMappingStep("left", "Press DPAD LEFT"),
    ButtonMappingStep("right", "Press DPAD RIGHT"),
    ButtonMappingStep("start", "Press START"),
    ButtonMappingStep("select", "Press SELECT"),
    ButtonMappingStep("l1", "Press L1"),
    ButtonMappingStep("r1", "Press R1"),
)


async def check_manual_mapping_shortcut(renderer, input_device) -> bool:
    held_buttons: set[int] = set()
    restart_hold_started: float | None = None
    saw_activity = False
    started = time.time()

    while True:
        now = time.time()
        elapsed = now - started
        if elapsed >= SHORTCUT_POLL_WINDOW_SECONDS:
            return False
        if not saw_activity and elapsed >= SHORTCUT_IDLE_WINDOW_SECONDS:
            return False

        seconds_left = max(0, int(RESTART_HOLD_SECONDS - max(0.0, (now - restart_hold_started) if restart_hold_started is not None else 0.0)))
        renderer.clear()
        renderer.draw_title("Oi — STARTUP", online=False)
        lines = [
            "Hold any 2 buttons now to remap controls.",
            "",
            f"Controller: {input_device.controller_name()}",
            "",
            "Keep holding for 3 seconds to force button setup.",
        ]
        if restart_hold_started is not None:
            lines.append(f"Opening setup in {seconds_left}s...")
        renderer.draw_card("Startup", lines, 0, ascii_bg_lines=["[ remap ]"])
        renderer.draw_hints("Hold any 2 buttons=Remap")
        renderer.present()

        for event in input_device.poll_raw():
            if event.type == "quit":
                return False
            if event.type == "button":
                saw_activity = True
            restart_hold_started, restart_now = _update_restart_hold(held_buttons, restart_hold_started, event, time.time())
            if restart_now:
                return True

        await asyncio.sleep(0.033)


async def run_button_mapping_wizard(renderer, input_device, seed_map: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]] | None:
    mapping = {k: dict(v) for k, v in (seed_map or {}).items()}
    step_index = 0
    step_started = time.time()
    held_buttons: set[int] = set()
    restart_hold_started: float | None = None
    release_guard: tuple[str, int, int] | None = None
    last_press_signature: tuple[str, int, int] | None = None
    last_press_at = 0.0
    status_message = ""
    status_until = 0.0

    while step_index < len(BUTTON_MAPPING_STEPS):
        step = BUTTON_MAPPING_STEPS[step_index]
        now = time.time()
        elapsed = now - step_started
        seconds_left = max(0, 10 - int(elapsed))
        restart_seconds = 0
        if restart_hold_started is not None:
            restart_seconds = max(0, int(RESTART_HOLD_SECONDS - (now - restart_hold_started)))

        renderer.clear()
        renderer.draw_title("Oi — BUTTON SETUP", online=False)
        lines = [
            f"Step {step_index + 1}/{len(BUTTON_MAPPING_STEPS)}",
            "",
            step.prompt,
            "",
            "Press the requested control now.",
            f"Timeout: {seconds_left}s (keeps current/default mapping)",
            "",
            f"Controller: {input_device.controller_name()}",
            "Release the last control before the next step.",
            "Hold any 2 buttons for 3s to restart setup.",
        ]
        if restart_hold_started is not None:
            lines.append(f"Restarting setup in {restart_seconds}s...")
        if status_message and now < status_until:
            lines.append("")
            lines.append(status_message)
        renderer.draw_card("Button Setup", lines, 0, ascii_bg_lines=["[ map ]", "buttons"])
        renderer.draw_hints("Press control  Release after each step  2 buttons=Restart  Q/Esc=Cancel")
        renderer.present()

        step_advanced = False
        for event in input_device.poll_raw():
            if event.type == "quit":
                return None

            event_now = time.time()
            restart_hold_started, restart_now = _update_restart_hold(held_buttons, restart_hold_started, event, event_now)
            if restart_now:
                mapping = {}
                step_index = 0
                step_started = event_now
                held_buttons.clear()
                restart_hold_started = None
                release_guard = None
                last_press_signature = None
                last_press_at = 0.0
                status_message = "Restarted setup from step 1."
                status_until = event_now + 1.5
                step_advanced = False
                break

            release_guard = _advance_release_guard(release_guard, event)
            if release_guard is not None:
                continue

            if _is_duplicate_press(event, last_press_signature, last_press_at, event_now):
                continue

            resolved = _resolve_mapping_event(event)
            if resolved is None:
                continue

            signature = _mapping_signature(resolved)
            last_press_signature = signature
            last_press_at = event_now

            collision = _find_collision(mapping, step.logical_name, resolved)
            if collision is not None:
                status_message = f"Already used by {collision.upper()}; try another control."
                status_until = event_now + 1.8
                release_guard = signature
                continue

            mapping[step.logical_name] = resolved
            release_guard = signature
            step_index += 1
            step_started = event_now
            status_message = f"Mapped {step.logical_name.upper()} to {_describe_mapping(resolved)}"
            status_until = event_now + 0.8
            step_advanced = True

        if step_index >= len(BUTTON_MAPPING_STEPS):
            break
        if elapsed >= 10.0 and not step_advanced:
            step_index += 1
            step_started = time.time()
            held_buttons.clear()
            restart_hold_started = None
            release_guard = None
            last_press_signature = None
            last_press_at = 0.0
        await asyncio.sleep(0.033)

    return mapping


def _update_restart_hold(
    held_buttons: set[int],
    restart_hold_started: float | None,
    event: RawInputEvent,
    now: float,
) -> tuple[float | None, bool]:
    if event.type != "button":
        return restart_hold_started, False
    if event.action == "pressed":
        held_buttons.add(int(event.value))
    elif event.action == "released":
        held_buttons.discard(int(event.value))

    if len(held_buttons) >= 2:
        if restart_hold_started is None:
            restart_hold_started = now
        elif now - restart_hold_started >= RESTART_HOLD_SECONDS:
            return None, True
    else:
        restart_hold_started = None

    return restart_hold_started, False


def _resolve_mapping_event(event: RawInputEvent) -> dict[str, int] | None:
    if event.action != "pressed":
        return None
    if event.type == "button":
        return {"type": "button", "value": int(event.value)}
    if event.type == "hat" and int(event.value) != 0:
        return {"type": "hat", "hat": int(event.hat), "value": int(event.value)}
    return None


def _mapping_signature(mapping: dict[str, int]) -> tuple[str, int, int]:
    if mapping["type"] == "button":
        return ("button", int(mapping["value"]), 0)
    return ("hat", int(mapping.get("hat", 0)), int(mapping["value"]))


def _find_collision(
    mapping: dict[str, dict[str, Any]],
    logical_name: str,
    candidate: dict[str, int],
) -> str | None:
    candidate_sig = _mapping_signature(candidate)
    for other_name, other_mapping in mapping.items():
        if other_name == logical_name:
            continue
        if _mapping_signature(other_mapping) == candidate_sig:
            return other_name
    return None


def _advance_release_guard(
    release_guard: tuple[str, int, int] | None,
    event: RawInputEvent,
) -> tuple[str, int, int] | None:
    if release_guard is None:
        return None
    kind, a, b = release_guard
    if kind == "button" and event.type == "button" and event.action == "released" and int(event.value) == a:
        return None
    if kind == "hat" and event.type == "hat" and int(event.hat) == a and event.action == "released":
        return None
    return release_guard


def _is_duplicate_press(
    event: RawInputEvent,
    last_press_signature: tuple[str, int, int] | None,
    last_press_at: float,
    now: float,
) -> bool:
    resolved = _resolve_mapping_event(event)
    if resolved is None or last_press_signature is None:
        return False
    return _mapping_signature(resolved) == last_press_signature and (now - last_press_at) <= DEBOUNCE_SECONDS


def _describe_mapping(mapping: dict[str, int]) -> str:
    if mapping["type"] == "button":
        return f"button {mapping['value']}"
    return f"hat {mapping.get('hat', 0)}={mapping['value']}"
