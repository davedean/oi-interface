from __future__ import annotations

from types import SimpleNamespace

import pytest

from sim.streaming_repl import StreamingOiSimREPL


class FakeSim:
    def __init__(self):
        self.received_commands = []
        self.received_messages = []
        self.is_connected = True
        self.state = SimpleNamespace(value="THINKING")
        self.display_state = None
        self.display_label = None
        self.muted_until = None
        self.volume = 50
        self.brightness = 128
        self.calls = []

    async def send_text_prompt(self, text):
        self.calls.append(("text", text))


@pytest.fixture
def fake_sim():
    return FakeSim()


@pytest.fixture
def repl(fake_sim):
    app = StreamingOiSimREPL(gateway="ws://fake", device_id="test")
    app.sim = fake_sim
    return app


@pytest.mark.asyncio
async def test_receive_loop_renders_progress_streaming_and_cards(repl, fake_sim, capsys, monkeypatch):
    fake_sim.received_commands = [
        {"op": "display.show_progress", "args": {"text": "thinking..."}},
        {"op": "display.show_response_delta", "args": {"text_delta": "Hello", "is_final": False}},
        {"op": "display.show_response_delta", "args": {"text_delta": " world", "is_final": True}},
        {"op": "display.show_response_delta", "args": {"text_delta": "\n[thinking] calling tool\n", "is_final": False}},
        {"op": "display.show_card", "args": {"title": "Done", "body": "Answer"}},
    ]
    repl.running = True

    async def fake_sleep(_):
        repl.running = False

    monkeypatch.setattr("sim.streaming_repl.asyncio.sleep", fake_sleep)

    await repl._receive_loop()
    out = capsys.readouterr().out

    assert "⚙️  thinking..." in out
    assert "Hello world" in out
    assert "⚙️  [thinking] calling tool" in out
    assert "📥 display.show_card" in out
    assert "title: Done" in out
    assert "body: Answer" in out
    assert repl.current_response_text == ""
    assert repl._printed_command_count == len(fake_sim.received_commands)


@pytest.mark.asyncio
async def test_cmd_text_prints_streaming_preamble_and_resets_buffer(repl, fake_sim, capsys):
    repl.current_response_text = "stale"

    await repl._cmd_text(["hello", "there"])
    out = capsys.readouterr().out

    assert fake_sim.calls == [("text", "hello there")]
    assert repl.current_response_text == ""
    assert '📤 text.prompt (text="hello there")' in out
    assert "📥 State: THINKING" in out
    assert "💬 Agent:" in out


@pytest.mark.asyncio
async def test_cmd_text_usage(repl, capsys):
    await repl._cmd_text([])
    out = capsys.readouterr().out
    assert "Usage: text <message>" in out
    assert "Example: text what time is it?" in out


@pytest.mark.asyncio
async def test_cmd_events_reports_empty_and_mixed_history(repl, fake_sim, capsys):
    await repl._cmd_events([])
    empty_out = capsys.readouterr().out

    fake_sim.received_messages = [
        {"type": "command", "payload": {"op": "display.show_card"}},
        {"type": "event", "payload": {"event": "agent_response_delta", "text_delta": "Hello world"}},
        {"type": "event", "payload": {"event": "button.pressed"}},
    ]
    await repl._cmd_events([])
    out = capsys.readouterr().out

    assert "No events yet" in empty_out
    assert "Last 3 messages:" in out
    assert "📥 display.show_card" in out
    assert "📤 agent_response_delta: 'Hello world'..." in out
    assert "📤 button.pressed" in out


@pytest.mark.asyncio
async def test_cmd_help_mentions_streaming(repl, capsys):
    await repl._cmd_help([])
    out = capsys.readouterr().out
    assert "shows streaming response!" in out
    assert "Streaming: Agent responses appear in real-time" in out


@pytest.mark.asyncio
async def test_main_parses_args_and_starts(monkeypatch):
    called = {}

    class FakeStreamingRepl:
        def __init__(self, gateway, device_id):
            called["gateway"] = gateway
            called["device_id"] = device_id

        async def start(self):
            called["started"] = True

    monkeypatch.setattr("sim.streaming_repl.StreamingOiSimREPL", FakeStreamingRepl)
    monkeypatch.setattr("sys.argv", ["oi-sim-streaming", "--gateway", "ws://gw", "--device-id", "dev-2"])

    from sim import streaming_repl as streaming_module

    await streaming_module.main()

    assert called == {"gateway": "ws://gw", "device_id": "dev-2", "started": True}


def test_streaming_repl_inherits_from_base_and_initializes_fields(repl):
    assert repl.streaming_active is False
    assert repl.current_response_text == ""
