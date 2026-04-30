from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oi_client.capabilities import SUPPORTED_COMMANDS  # noqa: E402
from oi_client.state import State, StateMachine  # noqa: E402


ARG_BY_COMMAND = {
    "display.show_status": {"state": "thinking", "label": "Working"},
    "display.show_card": {"title": "T", "body": "B"},
    "display.show_progress": {"text": "step"},
    "display.show_response_delta": {"text_delta": "hi", "is_final": False},
    "character.set_state": {"label": "idle"},
    "audio.cache.put_begin": {"response_id": "r1"},
    "audio.cache.put_chunk": {"response_id": "r1", "seq": 0, "data_b64": "AAAA"},
    "audio.cache.put_end": {"response_id": "r1"},
    "audio.play": {"response_id": "r1"},
    "audio.stop": {},
    "device.set_brightness": {"value": 10},
    "device.mute_until": {"until": "2099-01-01T00:00:00.000Z"},
    "device.set_volume": {"level": 10},
    "device.set_led": {"enabled": True},
    "device.reboot": {},
    "device.shutdown": {},
    "storage.format": {},
    "wifi.configure": {"ssid": "demo"},
}


def test_every_advertised_command_has_sample_args_and_is_state_machine_safe() -> None:
    missing = [command for command in SUPPORTED_COMMANDS if command not in ARG_BY_COMMAND]
    assert missing == []

    setup_states = {
        "display.show_card": State.THINKING,
        "audio.play": State.RESPONSE_CACHED,
        "audio.stop": State.PLAYING,
        "device.mute_until": State.READY,
    }
    setup_steps = {
        "audio.cache.put_chunk": ["audio.cache.put_begin"],
        "audio.cache.put_end": ["audio.cache.put_begin"],
    }

    for command in SUPPORTED_COMMANDS:
        machine = StateMachine(setup_states.get(command, State.READY))
        for setup_command in setup_steps.get(command, []):
            machine.receive_command(setup_command, ARG_BY_COMMAND[setup_command])
        machine.receive_command(command, ARG_BY_COMMAND[command])
