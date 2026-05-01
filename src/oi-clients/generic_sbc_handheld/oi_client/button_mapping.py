from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from oi_client.input import RawInputEvent


RESTART_HOLD_SECONDS = 3.0


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


async def run_button_mapping_wizard(renderer, input_device, seed_map: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]] | None:
    mapping = {k: dict(v) for k, v in (seed_map or {}).items()}
    step_index = 0
    step_started = time.time()
    held_buttons: set[int] = set()
    restart_hold_started: float | None = None
    restart_flash_until = 0.0

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
            "Hold any 2 buttons for 3s to restart setup.",
        ]
        if restart_hold_started is not None and now < restart_flash_until:
            lines.append(f"Restarting setup in {restart_seconds}s...")
        renderer.draw_card("Button Setup", lines, 0, ascii_bg_lines=["[ map ]", "buttons"])
        renderer.draw_hints("Press control  Hold any 2 buttons=Restart  Q/Esc=Cancel")
        renderer.present()

        for event in input_device.poll_raw():
            if event.type == "quit":
                return None

            restart_hold_started, restart_now = _update_restart_hold(
                held_buttons,
                restart_hold_started,
                event,
                time.time(),
            )
            if restart_hold_started is not None:
                restart_flash_until = time.time() + 0.2
            if restart_now:
                mapping = {}
                step_index = 0
                step_started = time.time()
                held_buttons.clear()
                restart_hold_started = None
                restart_flash_until = time.time() + 0.5
                break

            resolved = _resolve_mapping_event(event)
            if resolved is None:
                continue
            mapping[step.logical_name] = resolved
            step_index += 1
            step_started = time.time()
            held_buttons.clear()
            restart_hold_started = None
            restart_flash_until = time.time() + 0.2
            break
        else:
            if elapsed >= 10.0:
                step_index += 1
                step_started = time.time()
                held_buttons.clear()
                restart_hold_started = None
            await asyncio.sleep(0.033)
            continue

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
