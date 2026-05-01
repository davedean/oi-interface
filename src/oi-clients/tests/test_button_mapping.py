from __future__ import annotations

from pathlib import Path
import sys

client_src = Path(__file__).parent.parent / "generic_sbc_handheld"
if str(client_src) not in sys.path:
    sys.path.insert(0, str(client_src))

from oi_client.button_mapping import RESTART_HOLD_SECONDS, _resolve_mapping_event, _update_restart_hold
from oi_client.input import RawInputEvent


def test_resolve_mapping_event_handles_button_and_hat() -> None:
    assert _resolve_mapping_event(RawInputEvent("button", "pressed", 4)) == {"type": "button", "value": 4}
    assert _resolve_mapping_event(RawInputEvent("hat", "pressed", 8, hat=1)) == {"type": "hat", "hat": 1, "value": 8}
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
