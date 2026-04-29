"""Tests for DATP command dispatcher."""
import asyncio
from pathlib import Path

import pytest

# Add the gateway and sim source to path for imports
import sys

gateway_src = Path(__file__).parent.parent / "src"
sim_src = Path(__file__).parent.parent.parent / "oi-sim" / "src"
sys.path.insert(0, str(gateway_src))
sys.path.insert(0, str(sim_src))

from datp import CommandDispatcher
from datp.server import DATPServer
from sim.sim import OiSim
from sim.state import State


@pytest.fixture
async def datp_server():
    """Start an ephemeral DATP server."""
    srv = DATPServer(host="localhost", port=0)
    task = asyncio.create_task(srv.start())
    await asyncio.sleep(0.15)  # allow bind
    yield srv
    await srv.stop()
    await asyncio.sleep(0.1)


@pytest.fixture
async def sim(datp_server):
    """Connect a virtual device to the DATP server."""
    device = OiSim(
        gateway=f"ws://localhost:{datp_server.port}/datp",
        device_id="oi-sim-cmd-test",
    )
    await device.connect()
    yield device
    await device.disconnect()


@pytest.fixture
async def dispatcher(datp_server):
    """Create a command dispatcher for the server."""
    return CommandDispatcher(datp_server)


# ------------------------------------------------------------------
# Tests: Display Commands
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_show_status_acked(dispatcher, sim):
    """Send display.show_status and verify ack."""
    ok = await dispatcher.show_status(
        "oi-sim-cmd-test",
        state="thinking",
    )
    assert ok is True


@pytest.mark.asyncio
async def test_show_status_updates_sim_display_state(dispatcher, sim):
    """Verify that display.show_status updates device's display_state property."""
    assert sim.display_state is None

    ok = await dispatcher.show_status("oi-sim-cmd-test", state="thinking")
    assert ok is True
    assert sim.display_state == "thinking"

    ok = await dispatcher.show_status("oi-sim-cmd-test", state="response_cached", label="Ready")
    assert ok is True
    assert sim.display_state == "response_cached"
    assert sim.display_label == "Ready"


@pytest.mark.asyncio
async def test_show_card_acked(dispatcher, sim):
    """Send display.show_card and verify ack."""
    options = [
        {"id": "approve", "label": "Approve"},
        {"id": "deny", "label": "Deny"},
    ]
    ok = await dispatcher.show_card("oi-sim-cmd-test", title="Apply patch?", options=options)
    assert ok is True


# ------------------------------------------------------------------
# Tests: Audio Cache Sequence
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audio_cache_sequence_transitions_response_cached(dispatcher, sim):
    """Verify that cache put_begin + chunk + put_end transitions THINKING → RESPONSE_CACHED."""
    # First, move device to THINKING state (simulate receiving a prompt)
    # Use private _state to bypass transition validation (for testing only)
    sim._state_machine._state = State.THINKING
    assert sim.state == State.THINKING

    # Start cache sequence
    ok = await dispatcher.cache_put_begin("oi-sim-cmd-test", response_id="resp_001")
    assert ok is True
    assert sim.state == State.THINKING  # stays in THINKING during cache

    # Send a chunk
    ok = await dispatcher.cache_put_chunk(
        "oi-sim-cmd-test",
        response_id="resp_001",
        seq=0,
        data_b64="AAAA",  # minimal dummy base64
    )
    assert ok is True
    assert sim.state == State.THINKING

    # Complete cache sequence
    ok = await dispatcher.cache_put_end("oi-sim-cmd-test", response_id="resp_001", sha256=None)
    assert ok is True
    assert sim.state == State.RESPONSE_CACHED  # transitions on put_end


@pytest.mark.asyncio
async def test_audio_cache_chunk_count_tracked(dispatcher, sim):
    """Verify cache chunk count is tracked."""
    sim._state_machine._state = State.THINKING

    await dispatcher.cache_put_begin("oi-sim-cmd-test", response_id="resp_001")
    assert sim._state_machine._cache_chunk_count == 0

    await dispatcher.cache_put_chunk(
        "oi-sim-cmd-test", response_id="resp_001", seq=0, data_b64="AAAA"
    )
    assert sim._state_machine._cache_chunk_count == 1

    await dispatcher.cache_put_chunk(
        "oi-sim-cmd-test", response_id="resp_001", seq=1, data_b64="BBBB"
    )
    assert sim._state_machine._cache_chunk_count == 2

    await dispatcher.cache_put_end("oi-sim-cmd-test", response_id="resp_001", sha256=None)
    assert sim._state_machine._caching is False


# ------------------------------------------------------------------
# Tests: Audio Playback
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audio_play_transitions_playing(dispatcher, sim):
    """Verify audio.play transitions to PLAYING state."""
    # First cache some audio
    sim._state_machine._state = State.THINKING
    await dispatcher.cache_put_begin("oi-sim-cmd-test", response_id="resp_001")
    await dispatcher.cache_put_end("oi-sim-cmd-test", response_id="resp_001", sha256=None)
    assert sim.state == State.RESPONSE_CACHED

    # Play the cached audio
    ok = await dispatcher.audio_play("oi-sim-cmd-test")
    assert ok is True
    assert sim.state == State.PLAYING


@pytest.mark.asyncio
async def test_audio_stop_transitions_ready(dispatcher, sim):
    """Verify audio.stop transitions to READY state."""
    # Move device to PLAYING (use direct state setting for testing)
    sim._state_machine._state = State.PLAYING
    assert sim.state == State.PLAYING

    # Stop playback
    ok = await dispatcher.audio_stop("oi-sim-cmd-test")
    assert ok is True
    assert sim.state == State.READY


@pytest.mark.asyncio
async def test_audio_play_idempotent_when_already_playing(dispatcher, sim):
    """Verify audio.play is idempotent if device is already PLAYING."""
    sim._state_machine._state = State.PLAYING

    ok = await dispatcher.audio_play("oi-sim-cmd-test")
    assert ok is True
    assert sim.state == State.PLAYING  # still PLAYING, no error


@pytest.mark.asyncio
async def test_audio_stop_idempotent_when_already_ready(dispatcher, sim):
    """Verify audio.stop is idempotent if device is already READY."""
    assert sim.state == State.READY

    ok = await dispatcher.audio_stop("oi-sim-cmd-test")
    assert ok is True
    assert sim.state == State.READY


# ------------------------------------------------------------------
# Tests: Device Control
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mute_until_transitions_muted(dispatcher, sim):
    """Verify device.mute_until transitions to MUTED state."""
    assert sim.state == State.READY

    ok = await dispatcher.mute_until("oi-sim-cmd-test", until="2026-04-28T16:00:00.000Z")
    assert ok is True
    assert sim.state == State.MUTED
    assert sim.muted_until == "2026-04-28T16:00:00.000Z"


@pytest.mark.asyncio
async def test_set_brightness_acked_no_state_change(dispatcher, sim):
    """Verify device.set_brightness acks without changing state."""
    original_state = sim.state

    ok = await dispatcher.set_brightness("oi-sim-cmd-test", level=128)
    assert ok is True
    assert sim.state == original_state  # no state change


# ------------------------------------------------------------------
# Tests: Error Handling
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_to_unknown_device_returns_false(dispatcher):
    """Verify sending to unknown device returns False gracefully."""
    ok = await dispatcher.show_status("unknown-device-xyz", state="thinking")
    assert ok is False


@pytest.mark.asyncio
async def test_send_command_timeout_returns_false(dispatcher, sim):
    """Verify command timeout returns False (no ack received within timeout)."""
    # Disconnect the device so it can't ack
    await sim.disconnect()
    await asyncio.sleep(0.1)

    # Try to send — will timeout waiting for ack
    ok = await dispatcher.show_status("oi-sim-cmd-test", state="thinking", timeout=0.5)
    assert ok is False


# ------------------------------------------------------------------
# Tests: Command Recording
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_device_records_received_commands(dispatcher, sim):
    """Verify OiSim records all received commands."""
    await dispatcher.show_status("oi-sim-cmd-test", state="thinking")
    await dispatcher.show_status("oi-sim-cmd-test", state="response_cached")
    await dispatcher.set_brightness("oi-sim-cmd-test", level=100)

    commands = sim.received_commands
    assert len(commands) == 3
    assert commands[0]["op"] == "display.show_status"
    assert commands[1]["op"] == "display.show_status"
    assert commands[2]["op"] == "device.set_brightness"
