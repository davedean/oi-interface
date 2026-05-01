"""Fixture loading and replay tests for oi-sim."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.fixtures import load_fixture, replay_fixture
from sim.sim import OiSim


@pytest.mark.asyncio
async def test_replay_fixture_default_injects_commands_into_connected_sim(datp_server, tmp_path: Path):
    """replay_fixture should use direct injection by default for live sims."""
    fixture = tmp_path / "replay.jsonl"
    fixture.write_text(
        '{"type":"command","id":"cmd-1","payload":{"op":"display.show_status","args":{"state":"thinking","label":"Replay"}}}\n',
        encoding="utf-8",
    )
    device = OiSim(gateway=f"ws://localhost:{datp_server.port}/datp", device_id="oi-sim-replay")
    await device.connect()

    try:
        received = await replay_fixture(device, str(fixture))

        assert received[0]["payload"]["op"] == "display.show_status"
        assert device.display_state == "thinking"
        assert device.display_label == "Replay"
        assert device.received_commands[0]["op"] == "display.show_status"
    finally:
        await device.disconnect()


class TestFixtures:
    def test_load_fixture_valid(self, tmp_path):
        """load_fixture parses a valid JSONL file."""
        fixture = tmp_path / "test.jsonl"
        fixture.write_text(
            '{"type":"command","payload":{"op":"display.show_status"}}\n'
            '{"type":"command","payload":{"op":"audio.play"}}\n'
        )
        result = load_fixture(str(fixture))
        assert len(result) == 2
        assert result[0]["payload"]["op"] == "display.show_status"

    def test_load_fixture_missing_file(self):
        """FileNotFoundError for missing fixture."""
        with pytest.raises(FileNotFoundError):
            load_fixture("/no/such/file.jsonl")

    def test_load_fixture_invalid_json(self, tmp_path):
        """ValueError for non-JSON lines."""
        fixture = tmp_path / "bad.jsonl"
