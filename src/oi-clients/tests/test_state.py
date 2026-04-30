"""Tests for the handheld state machine."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


client_src = Path(__file__).parent.parent / "generic_sbc_handheld"
if str(client_src) not in sys.path:
    sys.path.insert(0, str(client_src))

from oi_client.state import InvalidTransition, State, StateMachine


def test_valid_transition_updates_state() -> None:
    machine = StateMachine(State.READY)

    result = machine.transition(State.RECORDING)

    assert result == State.RECORDING
    assert machine.state == State.RECORDING


def test_invalid_transition_raises_with_context() -> None:
    machine = StateMachine(State.READY)

    with pytest.raises(InvalidTransition) as exc:
        machine.transition(State.PLAYING)

    assert exc.value.from_state == State.READY
    assert exc.value.to_state == State.PLAYING
    assert "READY" in str(exc.value)


def test_display_show_card_advances_thinking_to_response_cached() -> None:
    machine = StateMachine(State.THINKING)

    state = machine.receive_command("display.show_card", {"title": "Done"})

    assert state == State.RESPONSE_CACHED
    assert machine.state == State.RESPONSE_CACHED


def test_audio_cache_sequence_tracks_chunks_and_completes() -> None:
    machine = StateMachine(State.THINKING)

    assert machine.receive_command("audio.cache.put_begin") == State.THINKING
    assert machine._caching is True
    assert machine.receive_command("audio.cache.put_chunk") == State.THINKING
    assert machine._cache_chunk_count == 1

    state = machine.receive_command("audio.cache.put_end")

    assert state == State.RESPONSE_CACHED
    assert machine.state == State.RESPONSE_CACHED
    assert machine._caching is False


def test_audio_play_and_stop_are_idempotent() -> None:
    machine = StateMachine(State.RESPONSE_CACHED)

    assert machine.receive_command("audio.play") == State.PLAYING
    assert machine.receive_command("audio.play") == State.PLAYING
    assert machine.receive_command("audio.stop") == State.READY
    assert machine.receive_command("audio.stop") == State.READY


def test_device_setting_commands_update_properties_without_state_change() -> None:
    machine = StateMachine(State.READY)

    assert machine.receive_command("device.set_volume", {"level": 25}) == State.READY
    assert machine.receive_command("device.set_led", {"enabled": False}) == State.READY
    assert machine.receive_command("device.set_brightness", {"value": 60}) == State.READY

    assert machine.volume == 25
    assert machine.led_enabled is False
    assert machine.brightness == 60
    assert machine.state == State.READY


def test_device_mute_and_reboot_transitions() -> None:
    machine = StateMachine(State.READY)

    assert machine.receive_command("device.mute_until", {"until": "later"}) == State.MUTED
    assert machine.receive_command("device.reboot") == State.BOOTING


def test_unknown_command_is_noop() -> None:
    machine = StateMachine(State.READY)

    assert machine.receive_command("unknown.op", {"x": 1}) == State.READY
    assert machine.state == State.READY


def test_assert_state_reports_actual_value() -> None:
    machine = StateMachine(State.READY)

    with pytest.raises(AssertionError, match="READY"):
        machine.assert_state(State.THINKING)
