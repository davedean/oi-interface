from __future__ import annotations

import asyncio
import json

import pytest

import sim
from sim.sim import OiSim
from sim.state import InvalidTransition, State, StateMachine


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.closed = False

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def close(self) -> None:
        self.closed = True


class TestStateMachineCoverage:
    def test_display_show_card_stays_put_when_response_cached_not_allowed(self):
        sm = StateMachine(State.READY)

        result = sm.receive_command("display.show_card", {"title": "done"})

        assert result == State.READY
        assert sm.state == State.READY

    def test_final_text_delta_stays_put_when_response_cached_not_allowed(self):
        sm = StateMachine(State.READY)

        result = sm.receive_command(
            "display.show_response_delta",
            {"text_delta": "done", "is_final": True},
        )

        assert result == State.READY
        assert sm.state == State.READY

    def test_audio_cache_sequence_transitions_to_response_cached(self):
        sm = StateMachine(State.THINKING)

        assert sm.receive_command("audio.cache.put_begin") == State.THINKING
        assert sm._caching is True
        assert sm._cache_chunk_count == 0

        assert sm.receive_command("audio.cache.put_chunk") == State.THINKING
        assert sm._cache_chunk_count == 1

        assert sm.receive_command("audio.cache.put_end") == State.RESPONSE_CACHED
        assert sm.state == State.RESPONSE_CACHED
        assert sm._caching is False

    def test_audio_cache_chunk_without_begin_is_noop(self):
        sm = StateMachine(State.THINKING)

        result = sm.receive_command("audio.cache.put_chunk")

        assert result == State.THINKING
        assert sm._cache_chunk_count == 0

    def test_audio_cache_end_clears_flag_without_transition_when_invalid(self):
        sm = StateMachine(State.READY)
        sm._caching = True

        result = sm.receive_command("audio.cache.put_end")

        assert result == State.READY
        assert sm.state == State.READY
        assert sm._caching is False

    def test_unknown_command_is_noop(self):
        sm = StateMachine(State.READY)

        assert sm.receive_command("future.command", {"x": 1}) == State.READY
        assert sm.state == State.READY


class TestOiSimUnitCoverage:
    def make_sim(self, *, strict: bool = False) -> tuple[OiSim, FakeWebSocket]:
        device = OiSim(gateway="ws://example.invalid/datp", strict=strict)
        ws = FakeWebSocket()
        device._ws = ws
        device._connected = True
        return device, ws

    @pytest.mark.asyncio
    async def test_process_message_non_strict_invalid_transition_logs_and_acks(self, caplog):
        device, ws = self.make_sim()
        msg = {
            "type": "command",
            "id": "cmd_1",
            "payload": {"op": "audio.play", "args": {}},
        }

        with caplog.at_level("DEBUG"):
            await device._process_message(msg)

        assert device.state == State.READY
        assert device.received_commands == [msg["payload"]]
        assert ws.sent[-1]["type"] == "ack"
        assert ws.sent[-1]["payload"] == {"command_id": "cmd_1", "ok": True}
        assert "Ignoring invalid transition" in caplog.text

    @pytest.mark.asyncio
    async def test_process_message_ack_resolves_pending_future(self):
        device, _ = self.make_sim()
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        device._pending_acks["cmd_2"] = fut

        await device._process_message({
            "type": "ack",
            "payload": {"command_id": "cmd_2", "ok": False},
        })

        assert fut.done() is True
        assert fut.result() is False
        assert "cmd_2" not in device._pending_acks

    @pytest.mark.asyncio
    async def test_process_message_error_transitions_to_error(self):
        device, _ = self.make_sim()

        await device._process_message({
            "type": "error",
            "payload": {"code": "BAD_GATEWAY", "message": "boom"},
        })

        assert device.state == State.ERROR

    @pytest.mark.asyncio
    async def test_process_message_error_swallows_invalid_transition(self, monkeypatch):
        device, _ = self.make_sim()

        def boom(self, new_state: State) -> State:
            raise InvalidTransition(State.READY, new_state)

        monkeypatch.setattr(StateMachine, "transition", boom)

        await device._process_message({
            "type": "error",
            "payload": {"code": "BAD_GATEWAY", "message": "boom"},
        })

        assert device.state == State.READY

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("initial_state", "expected_state"),
        [
            (State.PLAYING, State.RESPONSE_CACHED),
            (State.READY, State.READY),
        ],
    )
    async def test_send_playback_finished_transitions_only_from_playing(self, initial_state, expected_state):
        device, ws = self.make_sim()
        device._state_machine = StateMachine(initial_state)

        await device.send_playback_finished()

        assert device.state == expected_state
        assert ws.sent[-1]["payload"] == {
            "event": "audio.playback_finished",
            "response_id": "latest",
        }

    @pytest.mark.asyncio
    async def test_send_wifi_update_without_ssid_omits_field(self):
        device, ws = self.make_sim()

        await device.send_wifi_update(-61)

        assert ws.sent[-1]["payload"] == {
            "event": "sensor.wifi_update",
            "rssi": -61,
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("added", "removed", "expected_payload"),
        [
            (None, None, {"event": "device.capability_updated"}),
            (["mic"], None, {"event": "device.capability_updated", "added": ["mic"]}),
            (None, ["speaker"], {"event": "device.capability_updated", "removed": ["speaker"]}),
        ],
    )
    async def test_send_capability_updated_optional_fields(self, added, removed, expected_payload):
        device, ws = self.make_sim()

        await device.send_capability_updated(added=added, removed=removed)

        assert ws.sent[-1]["payload"] == expected_payload

    @pytest.mark.asyncio
    async def test_upload_audio_text_sends_placeholder_chunk(self):
        device, ws = self.make_sim()

        stream_id = await device.upload_audio_text("hello")

        payload = ws.sent[-1]["payload"]
        assert ws.sent[-1]["type"] == "audio_chunk"
        assert payload["stream_id"] == stream_id
        assert payload["seq"] == 0
        assert payload["format"] == "pcm16"
        assert payload["sample_rate"] == 16000
        assert payload["channels"] == 1
        assert payload["data_b64"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("arg", "expected_mode"),
        [
            (None, "READY"),
            (State.THINKING, "THINKING"),
            ("SAFE_MODE", "SAFE_MODE"),
        ],
    )
    async def test_send_state_report_normalizes_state_values(self, arg, expected_mode):
        device, ws = self.make_sim()

        await device.send_state_report(arg)

        assert ws.sent[-1]["type"] == "state"
        assert ws.sent[-1]["payload"]["mode"] == expected_mode

    def test_reset_for_reconnect_clears_session_and_buffers(self):
        device, _ = self.make_sim()
        device._session_id = "sess-1"
        device._pending_acks["cmd"] = object()  # type: ignore[assignment]
        device._received_commands.append({"op": "x"})
        device._received_messages.append({"type": "y"})

        device._reset_for_reconnect()

        assert device._session_id is None
        assert device._pending_acks == {}
        assert device.received_commands == []
        assert device.received_messages == []

    def test_package_exports_and_lazy_attributes(self):
        assert sim.__all__ == [
            "OiSim",
            "TraceEvent",
            "State",
            "InvalidTransition",
            "OiSimREPL",
        ]
        assert sim.__getattr__("OiSimREPL").__name__ == "OiSimREPL"
        with pytest.raises(AttributeError):
            sim.__getattr__("not_real")
