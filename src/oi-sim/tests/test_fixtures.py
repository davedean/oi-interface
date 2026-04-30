from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sim.fixtures import iter_fixture, load_fixture, replay_fixture
from sim.sim import OiSim
from sim.state import State


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


@pytest.fixture
def fixture_file(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.jsonl"
    path.write_text(
        '{"type":"command","id":"cmd-1","payload":{"op":"display.show_status","args":{"state":"thinking"}}}\n'
        '{"delay_ms":1}\n'
        '{"type":"ack","payload":{"command_id":"cmd-1","ok":true}}\n',
        encoding="utf-8",
    )
    return path


def test_load_fixture_skips_blank_lines(tmp_path: Path):
    path = tmp_path / "fixture.jsonl"
    path.write_text('\n{"type":"event","payload":{"event":"x"}}\n\n', encoding="utf-8")

    assert load_fixture(str(path)) == [{"type": "event", "payload": {"event": "x"}}]


@pytest.mark.asyncio
async def test_iter_fixture_streams_entries(fixture_file: Path):
    entries = []
    async for entry in iter_fixture(str(fixture_file)):
        entries.append(entry)

    assert len(entries) == 3
    assert entries[0]["payload"]["op"] == "display.show_status"
    assert entries[1]["delay_ms"] == 1


@pytest.mark.asyncio
async def test_replay_fixture_requires_connected_sim(tmp_path: Path):
    sim = OiSim()
    with pytest.raises(RuntimeError, match="must be connected"):
        await replay_fixture(sim, str(tmp_path / "missing.jsonl"))


@pytest.mark.asyncio
async def test_replay_fixture_direct_injection_updates_state_and_sends_ack(fixture_file: Path):
    sim = OiSim()
    sim._connected = True
    sim._ws = FakeWebSocket()
    sim._session_id = "sess-1"
    sim._state_machine = sim._state_machine.__class__(State.THINKING)

    received = await replay_fixture(sim, str(fixture_file), send_to_device=False)

    assert len(received) == 2
    assert sim.display_state == "thinking"
    assert sim.received_commands[0]["op"] == "display.show_status"
    assert sim._ws.sent[0]["type"] == "ack"
    assert sim._ws.sent[0]["payload"]["command_id"] == "cmd-1"


def test_iter_fixture_raises_for_invalid_json(tmp_path: Path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"type":"ok"}\nnot-json\n', encoding="utf-8")

    async def consume():
        async for _entry in iter_fixture(str(path)):
            pass

    with pytest.raises(ValueError, match="Invalid JSON"):
        import asyncio
        asyncio.run(consume())


@pytest.mark.asyncio
async def test_replay_fixture_sends_raw_messages_to_socket(fixture_file: Path):
    sim = OiSim()
    sim._connected = True
    sim._ws = FakeWebSocket()
    sim._session_id = "sess-1"

    received = await replay_fixture(sim, str(fixture_file), send_to_device=True)

    assert len(received) == 2
    assert sim._ws.sent[0]["type"] == "command"
    assert sim._ws.sent[1]["type"] == "ack"
