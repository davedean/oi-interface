"""State-machine focused tests for oi-sim."""
from __future__ import annotations

import pytest

from sim.state import InvalidTransition, State, StateMachine


class TestStateMachine:
    def test_initial_state(self):
        sm = StateMachine()
        assert sm.state == State.READY

    def test_initial_state_custom(self):
        sm = StateMachine(State.BOOTING)
        assert sm.state == State.BOOTING

    def test_valid_transition(self):
        sm = StateMachine(State.READY)
        sm.transition(State.RECORDING)
        assert sm.state == State.RECORDING

    def test_invalid_transition_raises(self):
        sm = StateMachine(State.READY)
        with pytest.raises(InvalidTransition) as exc_info:
            sm.transition(State.PLAYING)
        assert exc_info.value.from_state == State.READY
        assert exc_info.value.to_state == State.PLAYING

    def test_any_state_to_error(self):
        sm = StateMachine(State.RECORDING)
        sm.transition(State.ERROR)
        assert sm.state == State.ERROR

    def test_any_state_to_safe_mode(self):
        sm = StateMachine(State.THINKING)
        sm.transition(State.SAFE_MODE)
        assert sm.state == State.SAFE_MODE

    def test_booting_to_ready_or_offline(self):
        sm = StateMachine(State.BOOTING)
        sm.transition(State.READY)
        assert sm.state == State.READY

    def test_booting_to_pairing(self):
        """BOOTING → PAIRING is a valid transition (spec §5.1)."""
        sm = StateMachine(State.BOOTING)
        sm.transition(State.PAIRING)
        assert sm.state == State.PAIRING
        sm2 = StateMachine(State.BOOTING)
        sm2.transition(State.OFFLINE)
        assert sm2.state == State.OFFLINE

    def test_recording_to_uploading_or_ready(self):
        sm = StateMachine(State.RECORDING)
        sm.transition(State.UPLOADING)
        assert sm.state == State.UPLOADING
        sm2 = StateMachine(State.RECORDING)
        sm2.transition(State.READY)
        assert sm2.state == State.READY

    def test_uploading_to_thinking(self):
        sm = StateMachine(State.UPLOADING)
        sm.transition(State.THINKING)
        assert sm.state == State.THINKING

    def test_thinking_to_response_cached(self):
        sm = StateMachine(State.THINKING)
        sm.transition(State.RESPONSE_CACHED)
        assert sm.state == State.RESPONSE_CACHED

    def test_response_cached_to_playing(self):
        sm = StateMachine(State.RESPONSE_CACHED)
        sm.transition(State.PLAYING)
        assert sm.state == State.PLAYING
    
    def test_response_cached_to_thinking(self):
        sm = StateMachine(State.RESPONSE_CACHED)
        sm.transition(State.THINKING)
        assert sm.state == State.THINKING

    def test_playing_to_ready(self):
        sm = StateMachine(State.PLAYING)
        sm.transition(State.READY)
        assert sm.state == State.READY

    def test_assert_state_passes(self):
        sm = StateMachine(State.READY)
        sm.assert_state(State.READY)

    def test_assert_state_fails(self):
        sm = StateMachine(State.READY)
        with pytest.raises(AssertionError):
            sm.assert_state(State.RECORDING)

    def test_receive_command_no_change(self):
        sm = StateMachine(State.READY)
        result = sm.receive_command("display.show_status")
        assert result == State.READY

    def test_receive_command_audio_play_transitions(self):
        sm = StateMachine(State.RESPONSE_CACHED)
        result = sm.receive_command("audio.play")
        assert result == State.PLAYING
        assert sm.state == State.PLAYING

    def test_receive_command_audio_stop_to_ready(self):
        sm = StateMachine(State.PLAYING)
        result = sm.receive_command("audio.stop")
        assert result == State.READY

    def test_receive_command_mute_until(self):
        sm = StateMachine(State.READY)
        result = sm.receive_command("device.mute_until")
        assert result == State.MUTED

    def test_receive_command_display_show_card_transitions_from_thinking(self):
        sm = StateMachine(State.THINKING)
        result = sm.receive_command("display.show_card", {"title": "Response"})
        assert result == State.RESPONSE_CACHED
        assert sm.state == State.RESPONSE_CACHED

    def test_receive_command_display_text_delta_stays_in_thinking(self):
        """display.show_text_delta with is_final=False stays in current state."""
        sm = StateMachine(State.THINKING)
        result = sm.receive_command("display.show_text_delta", {"text_delta": "Hello", "is_final": False})
        assert result == State.THINKING
        assert sm.state == State.THINKING

    def test_receive_command_display_text_delta_final_transitions(self):
        """display.show_text_delta with is_final=True transitions to RESPONSE_CACHED."""
        sm = StateMachine(State.THINKING)
        result = sm.receive_command("display.show_text_delta", {"text_delta": "Hello", "is_final": True})
        assert result == State.RESPONSE_CACHED
        assert sm.state == State.RESPONSE_CACHED

    def test_receive_command_audio_play_idempotent(self):
        """audio.play from PLAYING is idempotent (no-op, not an error)."""
        sm = StateMachine(State.PLAYING)
        result = sm.receive_command("audio.play")
        assert result == State.PLAYING  # stayed in PLAYING, did not raise

    def test_receive_command_audio_stop_idempotent(self):
        """audio.stop from READY is idempotent (no-op, not an error)."""
        sm = StateMachine(State.READY)
        result = sm.receive_command("audio.stop")
        assert result == State.READY  # stayed in READY, did not raise


class TestStateMachineNewProperties:
    def test_volume_property_default(self):
        """StateMachine has default volume of 80."""
        sm = StateMachine()
        assert sm.volume == 80

    def test_volume_property_updated(self):
        """StateMachine volume can be updated via command."""
        sm = StateMachine()
        sm.receive_command("device.set_volume", {"level": 60})
        assert sm.volume == 60

    def test_led_enabled_property_default(self):
        """StateMachine has LED enabled by default."""
        sm = StateMachine()
        assert sm.led_enabled is True

    def test_led_enabled_property_updated(self):
        """StateMachine LED can be toggled via command."""
        sm = StateMachine()
        sm.receive_command("device.set_led", {"enabled": False})
        assert sm.led_enabled is False

    def test_brightness_property_default(self):
        """StateMachine has default brightness of 100."""
        sm = StateMachine()
        assert sm.brightness == 100

    def test_brightness_property_updated(self):
        """StateMachine brightness can be updated via command."""
        sm = StateMachine()
        sm.receive_command("device.set_brightness", {"value": 75})
        assert sm.brightness == 75
