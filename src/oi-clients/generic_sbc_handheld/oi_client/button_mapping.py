from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from oi_client.input import RawInputEvent


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

    for idx, step in enumerate(BUTTON_MAPPING_STEPS, start=1):
        started = time.time()
        while True:
            elapsed = time.time() - started
            seconds_left = max(0, 10 - int(elapsed))
            renderer.clear()
            renderer.draw_title("Oi — BUTTON SETUP", online=False)
            renderer.draw_card(
                "Button Setup",
                [
                    f"Step {idx}/{len(BUTTON_MAPPING_STEPS)}",
                    "",
                    step.prompt,
                    "",
                    "Press the requested control now.",
                    f"Timeout: {seconds_left}s (keeps current/default mapping)",
                    "",
                    f"Controller: {input_device.controller_name()}",
                ],
                0,
                ascii_bg_lines=["[ map ]", "buttons"],
            )
            renderer.draw_hints("Press requested control  Q/Esc=Cancel")
            renderer.present()

            for event in input_device.poll_raw():
                if event.type == "quit":
                    return None
                resolved = _resolve_mapping_event(event)
                if resolved is None:
                    continue
                mapping[step.logical_name] = resolved
                break
            else:
                if elapsed >= 10.0:
                    break
                await asyncio.sleep(0.033)
                continue
            break

    return mapping


def _resolve_mapping_event(event: RawInputEvent) -> dict[str, int] | None:
    if event.action != "pressed":
        return None
    if event.type == "button":
        return {"type": "button", "value": int(event.value)}
    if event.type == "hat" and int(event.value) != 0:
        return {"type": "hat", "hat": int(event.hat), "value": int(event.value)}
    return None
