from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from sim.repl import OiSimREPL


class FakeSim:
    def __init__(self) -> None:
        self.is_connected = True
        self.gateway = "ws://fake"
        self.received_commands: list[dict] = []
        self.received_messages: list[dict] = []
        self.state = SimpleNamespace(value="READY")
        self.display_state = "thinking"
        self.display_label = "Processing"
        self.muted_until = None
        self.volume = 50
        self.brightness = 80
        self.calls: list[tuple] = []
        self.fail_connect = False
        self.switch_gateway_result = True

    async def connect(self):
        self.calls.append(("connect",))
        if self.fail_connect:
            raise RuntimeError("boom")
        self.is_connected = True

    async def disconnect(self):
        self.calls.append(("disconnect",))
        self.is_connected = False

    async def switch_gateway(self, gateway):
        self.calls.append(("switch_gateway", gateway))
        if self.switch_gateway_result:
            self.gateway = gateway
        return self.switch_gateway_result

    async def press_long_hold(self):
        self.calls.append(("hold",))

    async def release(self):
        self.calls.append(("release",))

    async def press_button(self):
        self.calls.append(("tap",))

    async def double_tap(self):
        self.calls.append(("double",))

    async def press_very_long_hold(self):
        self.calls.append(("mute",))

    async def send_playback_started(self, response_id):
        self.calls.append(("play", response_id))

    async def send_playback_finished(self):
        self.calls.append(("stop",))

    async def send_text_prompt(self, text):
        self.calls.append(("text", text))

    async def send_battery_update(self, percent):
        self.calls.append(("battery", percent))

    async def send_charging_started(self):
        self.calls.append(("charging", "start"))

    async def send_charging_stopped(self):
        self.calls.append(("charging", "stop"))

    async def send_wifi_update(self, rssi):
        self.calls.append(("wifi", rssi))


@pytest.fixture
def fake_sim():
    return FakeSim()


@pytest.fixture
def repl(fake_sim):
    app = OiSimREPL(gateway="ws://fake", device_id="test-device")
    app.sim = fake_sim
    return app


@pytest.mark.asyncio
async def test_receive_loop_prints_new_commands_once(repl, fake_sim, capsys, monkeypatch):
    fake_sim.received_commands = [
        {"op": "display.show_card", "args": {"title": "Hello", "body": "World"}},
        {"op": "display.show_status", "args": {}},
    ]
    repl.running = True

    async def fake_sleep(_):
        repl.running = False

    monkeypatch.setattr("sim.repl.asyncio.sleep", fake_sleep)

    await repl._receive_loop()
    out = capsys.readouterr().out

    assert "📥 display.show_card" in out
    assert "title: Hello" in out
    assert "body: World" in out
    assert "📥 display.show_status" in out
    assert repl._printed_command_count == 2


@pytest.mark.asyncio
async def test_handle_command_invalid_syntax(repl, capsys):
    await repl._handle_command('text "unterminated')
    assert "Invalid command syntax" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_handle_command_unknown(repl, capsys):
    await repl._handle_command("mystery")
    assert "Unknown command: mystery" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_handle_command_reports_command_errors(repl, fake_sim, capsys, monkeypatch):
    async def explode(_args):
        raise RuntimeError("bad command")

    monkeypatch.setattr(repl, "_cmd_hold", explode)
    await repl._handle_command("hold")

    assert "✗ Error: bad command" in capsys.readouterr().out


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("line", "expected_call", "expected_output"),
    [
        ("hold", ("hold",), "button.long_hold_started"),
        ("release", ("release",), "audio.recording_finished"),
        ("tap", ("tap",), "button.pressed"),
        ("double", ("double",), "button.double_tap"),
        ("mute", ("mute",), "button.very_long_hold_started"),
        ("play custom-1", ("play", "custom-1"), "audio.playback_started (response_id=custom-1)"),
        ("play", ("play", "latest"), "audio.playback_started (response_id=latest)"),
        ("stop", ("stop",), "audio.playback_finished"),
        ("text hello there", ("text", "hello there"), 'text.prompt (text="hello there")'),
        ("ask quoted words", ("text", "quoted words"), 'text.prompt (text="quoted words")'),
        ("battery 42", ("battery", 42), "sensor.battery_update (battery_percent=42)"),
        ("wifi -55", ("wifi", -55), "sensor.wifi_update (rssi=-55)"),
        ("disconnect", ("disconnect",), "✓ Disconnected"),
    ],
)
async def test_handle_command_routes_to_sim(repl, fake_sim, line, expected_call, expected_output, capsys):
    await repl._handle_command(line)
    out = capsys.readouterr().out

    assert fake_sim.calls[-1] == expected_call
    assert expected_output in out


@pytest.mark.asyncio
async def test_cmd_text_usage(repl, capsys):
    await repl._cmd_text([])
    out = capsys.readouterr().out
    assert "Usage: text <message>" in out
    assert "Example: text what time is it?" in out


@pytest.mark.asyncio
async def test_cmd_battery_usage(repl, capsys):
    await repl._cmd_battery([])
    assert "Usage: battery <0-100>" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cmd_charging_usage_and_modes(repl, fake_sim, capsys):
    await repl._cmd_charging([])
    usage_out = capsys.readouterr().out
    await repl._cmd_charging(["start"])
    start_out = capsys.readouterr().out
    await repl._cmd_charging(["stop"])
    stop_out = capsys.readouterr().out

    assert "Usage: charging start|stop" in usage_out
    assert ("charging", "start") in fake_sim.calls
    assert ("charging", "stop") in fake_sim.calls
    assert "📤 charging_started" in start_out
    assert "📤 charging_stopped" in stop_out


@pytest.mark.asyncio
async def test_cmd_wifi_usage(repl, capsys):
    await repl._cmd_wifi([])
    assert "Usage: wifi <-100 to 0>" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_cmd_connect_handles_already_connected_and_reconnects(repl, fake_sim, capsys):
    await repl._cmd_connect([])
    out1 = capsys.readouterr().out
    fake_sim.is_connected = False
    await repl._cmd_connect([])
    out2 = capsys.readouterr().out

    assert "Already connected" in out1
    assert "✓ Connected to ws://fake" in out2
    assert fake_sim.calls[-1] == ("connect",)


@pytest.mark.asyncio
async def test_cmd_connect_with_gateway_switches_when_connected(repl, fake_sim, capsys):
    await repl._cmd_connect(["ws://backup/datp"])
    out = capsys.readouterr().out

    assert fake_sim.calls[-1] == ("switch_gateway", "ws://backup/datp")
    assert fake_sim.gateway == "ws://backup/datp"
    assert repl.gateway == "ws://backup/datp"
    assert "✓ Switched gateway to ws://backup/datp" in out


@pytest.mark.asyncio
async def test_cmd_connect_with_gateway_updates_target_before_connecting(repl, fake_sim, capsys):
    fake_sim.is_connected = False

    await repl._cmd_connect(["ws://backup/datp"])
    out = capsys.readouterr().out

    assert fake_sim.gateway == "ws://backup/datp"
    assert repl.gateway == "ws://backup/datp"
    assert fake_sim.calls[-1] == ("connect",)
    assert "✓ Connected to ws://backup/datp" in out


@pytest.mark.asyncio
async def test_cmd_gateway_shows_sets_and_switches_gateway(repl, fake_sim, capsys):
    await repl._cmd_gateway([])
    show_out = capsys.readouterr().out

    fake_sim.is_connected = False
    await repl._cmd_gateway(["ws://offline/datp"])
    set_out = capsys.readouterr().out

    fake_sim.is_connected = True
    await repl._cmd_gateway(["ws://live/datp"])
    switch_out = capsys.readouterr().out

    assert "Gateway: ws://fake" in show_out
    assert fake_sim.gateway == "ws://live/datp"
    assert repl.gateway == "ws://live/datp"
    assert ("switch_gateway", "ws://live/datp") in fake_sim.calls
    assert "✓ Gateway set to ws://offline/datp" in set_out
    assert "✓ Switched gateway to ws://live/datp" in switch_out


@pytest.mark.asyncio
async def test_cmd_gateway_same_gateway_does_not_reset_printed_count(repl, fake_sim, capsys):
    fake_sim.switch_gateway_result = False
    repl._printed_command_count = 3

    await repl._cmd_gateway(["ws://fake"])
    out = capsys.readouterr().out

    assert repl._printed_command_count == 3
    assert "Gateway already set to ws://fake" in out


@pytest.mark.asyncio
async def test_cmd_state_prints_all_fields(repl, capsys):
    await repl._cmd_state([])
    out = capsys.readouterr().out
    assert "State: READY" in out
    assert "Display: thinking Processing" in out
    assert "Gateway: ws://fake" in out
    assert "Muted until: no" in out
    assert "Volume: 50" in out
    assert "Brightness: 80" in out


@pytest.mark.asyncio
async def test_cmd_events_empty_and_mixed_messages(repl, fake_sim, capsys):
    await repl._cmd_events([])
    empty_out = capsys.readouterr().out

    fake_sim.received_messages = [
        {"type": "command", "payload": {"op": "display.show_card"}},
        {"type": "event", "payload": {"event": "button.pressed"}},
        {"type": "ack", "payload": {}},
    ]
    await repl._cmd_events([])
    out = capsys.readouterr().out

    assert "No events yet" in empty_out
    assert "Last 3 of 3 messages:" in out
    assert "📥 display.show_card" in out
    assert "📤 button.pressed" in out
    assert "ack" in out


@pytest.mark.asyncio
async def test_cmd_help_and_quit(repl, capsys):
    repl.running = True
    await repl._cmd_help([])
    help_out = capsys.readouterr().out
    await repl._cmd_quit([])

    assert "Commands:" in help_out
    assert "text <msg>  - Send text prompt to agent" in help_out
    assert "gateway [url] - Show current gateway or switch to a new one" in help_out
    assert repl.running is False


@pytest.mark.asyncio
async def test_start_success_connects_runs_loop_and_disconnects(monkeypatch, capsys):
    fake_sim = FakeSim()

    monkeypatch.setattr("sim.repl.OiSim", lambda **kwargs: fake_sim)

    repl = OiSimREPL(gateway="ws://fake", device_id="abc")

    async def fake_receive_loop():
        return None

    async def fake_repl_loop():
        repl.running = False

    class FakeTask:
        def __init__(self, coro):
            self.coro = coro
            self.cancel_called = False
            self.awaited = False

        def cancel(self):
            self.cancel_called = True
            self.coro.close()

        def __await__(self):
            async def _await_task():
                self.awaited = True
                if self.cancel_called:
                    raise asyncio.CancelledError
                return None
            return _await_task().__await__()

    created_tasks: list[FakeTask] = []

    def fake_create_task(coro):
        task = FakeTask(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr(repl, "_receive_loop", fake_receive_loop)
    monkeypatch.setattr(repl, "_repl_loop", fake_repl_loop)
    monkeypatch.setattr("sim.repl.asyncio.create_task", fake_create_task)

    await repl.start()
    out = capsys.readouterr().out

    assert ("connect",) in fake_sim.calls
    assert ("disconnect",) in fake_sim.calls
    assert "Connecting to ws://fake..." in out
    assert "✓ Connected as abc" in out
    assert "✓ Disconnected" in out
    assert len(created_tasks) == 1
    assert created_tasks[0].cancel_called is True
    assert created_tasks[0].awaited is True


@pytest.mark.asyncio
async def test_repl_loop_handles_eof_stops_running(monkeypatch):
    repl = OiSimREPL()
    repl.running = True

    class FakeLoop:
        async def run_in_executor(self, *_args, **_kwargs):
            raise EOFError

    monkeypatch.setattr("sim.repl.asyncio.get_running_loop", lambda: FakeLoop())

    await repl._repl_loop()

    assert repl.running is False


@pytest.mark.asyncio
async def test_repl_loop_handles_keyboard_interrupt_then_quit(monkeypatch, capsys):
    repl = OiSimREPL()
    repl.running = True
    responses = iter([KeyboardInterrupt(), "quit"])

    class FakeLoop:
        async def run_in_executor(self, *_args, **_kwargs):
            result = next(responses)
            if isinstance(result, BaseException):
                raise result
            return result

    monkeypatch.setattr("sim.repl.asyncio.get_running_loop", lambda: FakeLoop())

    await repl._repl_loop()
    out = capsys.readouterr().out

    assert "(Use 'quit' to exit)" in out
    assert repl.running is False


@pytest.mark.asyncio
async def test_main_parses_args_and_starts(monkeypatch):
    called = {}

    class FakeRepl:
        def __init__(self, gateway, device_id):
            called["gateway"] = gateway
            called["device_id"] = device_id

        async def start(self):
            called["started"] = True

    monkeypatch.setattr("sim.repl.OiSimREPL", FakeRepl)
    monkeypatch.setattr("sys.argv", ["oi-sim", "--gateway", "ws://gw", "--device-id", "dev-1"])

    from sim import repl as repl_module

    await repl_module.main()

    assert called == {"gateway": "ws://gw", "device_id": "dev-1", "started": True}


@pytest.mark.asyncio
async def test_start_reports_connection_failure(monkeypatch, capsys):
    fake_sim = FakeSim()
    fake_sim.fail_connect = True
    monkeypatch.setattr("sim.repl.OiSim", lambda **kwargs: fake_sim)

    repl = OiSimREPL(gateway="ws://fake", device_id="abc")
    await repl.start()

    assert "✗ Connection failed: boom" in capsys.readouterr().out
