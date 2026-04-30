from __future__ import annotations

import asyncio
import json

import pytest

import sim
from sim.sim import DEFAULT_CAPABILITIES, OiSim
from sim.state import InvalidTransition, State, StateMachine


class FakeWebSocket:
    def __init__(self, recv_messages: list[dict] | None = None) -> None:
        self.sent: list[dict] = []
        self.closed = False
        self.recv_messages = list(recv_messages or [])

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        return json.dumps(self.recv_messages.pop(0))

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
    async def test_upload_audio_text_sizes_placeholder_from_text_length(self):
        device, ws = self.make_sim()

        await device.upload_audio_text("hi")
        short_payload = ws.sent[-1]["payload"]["data_b64"]

        await device.upload_audio_text("hello" * 100)
        long_payload = ws.sent[-1]["payload"]["data_b64"]

        assert len(long_payload) > len(short_payload)

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

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method_name", "args", "expected_payload"),
        [
            ("tap", (), {"event": "button.pressed", "button": "main"}),
            ("press_button", (), {"event": "button.pressed", "button": "main"}),
            ("send_playback_started", ("resp-1",), {"event": "audio.playback_started", "response_id": "resp-1"}),
            ("send_battery_low", (), {"event": "battery_low", "battery_percent": 10}),
            ("send_charging_started", (), {"event": "charging_started", "battery_percent": 15}),
            ("send_charging_stopped", (), {"event": "charging_stopped", "battery_percent": 100}),
            ("send_wifi_connected", ("CafeNet",), {"event": "wifi.connected", "ssid": "CafeNet", "rssi": -50}),
            ("send_wifi_disconnected", (), {"event": "wifi.disconnected"}),
            ("send_storage_available", (2048,), {"event": "storage.available", "bytes_free": 2048}),
            ("send_display_released", (), {"event": "display.released"}),
        ],
    )
    async def test_simple_event_helpers_emit_expected_payloads(self, method_name, args, expected_payload):
        device, ws = self.make_sim()

        method = getattr(device, method_name)
        await method(*args)

        assert ws.sent[-1]["type"] == "event"
        assert ws.sent[-1]["payload"] == expected_payload

    @pytest.mark.asyncio
    async def test_press_very_long_hold_transitions_and_sends_event(self):
        device, ws = self.make_sim()

        await device.press_very_long_hold()

        assert device.state == State.MUTED
        assert ws.sent[-1]["payload"] == {
            "event": "button.very_long_hold_started",
            "button": "main",
            "duration_ms": 3000,
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method_name", "args", "expected_code"),
        [
            ("simulate_wifi_error", (), "WIFI_ERROR"),
            ("simulate_timeout_error", (), "TIMEOUT"),
        ],
    )
    async def test_error_simulation_wrappers_emit_expected_codes(self, method_name, args, expected_code):
        device, ws = self.make_sim()

        await getattr(device, method_name)(*args)

        assert ws.sent[-1]["payload"]["event"] == "device.error"
        assert ws.sent[-1]["payload"]["code"] == expected_code

    @pytest.mark.asyncio
    async def test_connect_raises_when_handshake_does_not_return_hello_ack(self, monkeypatch):
        fake_ws = FakeWebSocket(recv_messages=[{"type": "event", "payload": {}}])

        async def fake_connect(_gateway):
            return fake_ws

        monkeypatch.setattr("sim.sim.websockets.connect", fake_connect)
        device = OiSim(gateway="ws://example.invalid/datp")

        with pytest.raises(RuntimeError, match="Expected hello_ack"):
            await device.connect()

        assert fake_ws.sent[0]["type"] == "hello"
        assert fake_ws.closed is True
        assert device.is_connected is False
        assert device._ws is None

    @pytest.mark.asyncio
    async def test_connect_populates_session_and_starts_listener(self, monkeypatch):
        fake_ws = FakeWebSocket(recv_messages=[{"type": "hello_ack", "payload": {"session_id": "sess-123"}}])

        async def fake_connect(_gateway):
            return fake_ws

        monkeypatch.setattr("sim.sim.websockets.connect", fake_connect)

        listener_started = asyncio.Event()

        async def fake_listen_loop():
            listener_started.set()

        device = OiSim(gateway="ws://example.invalid/datp")
        device._listen_loop = fake_listen_loop

        await device.connect()
        await listener_started.wait()

        assert device.is_connected is True
        assert device._session_id == "sess-123"
        await device.disconnect()

    def test_display_properties_proxy_state_machine_fields(self):
        device = OiSim()
        device._state_machine.receive_command("display.show_status", {"state": "thinking", "label": "Working"})
        device._state_machine.receive_command("device.mute_until", {"until": "later"})

        assert device.display_state == "thinking"
        assert device.display_label == "Working"
        assert device.muted_until == "later"

    def test_default_capabilities_are_deep_copied_per_instance(self):
        first = OiSim()
        second = OiSim()

        first.capabilities["input"].append("new-input")

        assert "new-input" not in second.capabilities["input"]
        assert "new-input" not in DEFAULT_CAPABILITIES["input"]

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
