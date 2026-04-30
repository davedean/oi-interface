from __future__ import annotations

from dataclasses import dataclass
from typing import Any

REQUIRED_COMMANDS = [
    "display.show_status",
    "display.show_card",
    "audio.cache.put_begin",
    "audio.cache.put_chunk",
    "audio.cache.put_end",
    "audio.play",
    "audio.stop",
    "device.set_brightness",
    "device.mute_until",
]

OPTIONAL_COMMANDS = [
    "display.show_progress",
    "display.show_response_delta",
    "character.set_state",
]

EXTENDED_COMMANDS = [
    "device.set_volume",
    "device.set_led",
]

RECOGNIZED_BUT_NOT_ADVERTISED_COMMANDS = [
    "device.reboot",
    "device.shutdown",
    "storage.format",
    "wifi.configure",
]

SUPPORTED_COMMANDS = REQUIRED_COMMANDS + OPTIONAL_COMMANDS + EXTENDED_COMMANDS


@dataclass(frozen=True)
class RuntimeAudioStatus:
    has_input: bool
    has_output: bool


def build_capabilities(audio_status: RuntimeAudioStatus, cols: int, rows: int) -> dict[str, Any]:
    input_caps = ["buttons", "dpad", "confirm_buttons"]
    if audio_status.has_input:
        input_caps.append("hold_to_record")

    return {
        "input": input_caps,
        "output": ["screen", "cached_audio"],
        "sensors": ["battery", "wifi_rssi"],
        "commands_supported": list(SUPPORTED_COMMANDS),
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
