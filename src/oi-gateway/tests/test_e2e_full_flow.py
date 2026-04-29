"""End-to-end integration tests connecting all components.

This test file verifies the full voice-to-audio pipeline:
1. Device uploads audio (chunks + recording_finished)
2. StreamAccumulator buffers and triggers transcription
3. ChannelService receives transcript and sends to pi agent
4. Pi returns response
5. AudioDeliveryPipeline runs TTS and caches audio to device
6. Device plays audio and transitions to appropriate state

Run from: src/oi-gateway/
Command: pytest tests/test_e2e_full_flow.py -v
"""
from __future__ import annotations

import asyncio
import base64
import tempfile
from pathlib import Path

import pytest

import sys
gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))
sim_src = Path(__file__).parent.parent.parent / "oi-sim" / "src"
sys.path.insert(0, str(sim_src))

from datp.server import DATPServer
from datp.commands import CommandDispatcher
from datp import EventBus
from registry import RegistryService
from registry.store import DeviceStore
from channel import ChannelService, StubPiBackend
from audio import StreamAccumulator, AudioDeliveryPipeline, StubTtsBackend
from sim.sim import OiSim, State


@pytest.fixture
async def gateway_stack():
    """Create a full gateway stack with all components wired."""
    # DATP server
    server = DATPServer(host="localhost", port=0)
    await server.start()
    
    # Registry with SQLite store
    store = DeviceStore()
    registry = RegistryService(store=store, event_bus=server.event_bus)
    server.registry = registry
    
    # Command dispatcher
    dispatcher = CommandDispatcher(server)
    
    # STT pipeline
    from audio import StubSttBackend
    stt_backend = StubSttBackend(response="transcribed text")
    stt_pipeline = StreamAccumulator(server.event_bus, stt_backend)
    
    # Pi backend (stub for testing)
    pi_backend = StubPiBackend(response="Agent response text")
    
    # Channel service (STT → pi) - subscribes in __init__
    channel_service = ChannelService(
        event_bus=server.event_bus,
        registry=registry,
        pi_backend=pi_backend,
    )
    
    # Audio delivery pipeline (pi response → TTS → device) - subscribes in __init__
    tts_backend = StubTtsBackend()
    delivery_pipeline = AudioDeliveryPipeline(
        event_bus=server.event_bus,
        dispatcher=dispatcher,
        tts=tts_backend,
    )
    
    yield {
        "server": server,
        "registry": registry,
        "dispatcher": dispatcher,
        "channel": channel_service,
        "pi_backend": pi_backend,
    }
    
    # Cleanup
    store.close()
    await server.stop()
    await asyncio.sleep(0.1)


@pytest.fixture
async def sim_device(gateway_stack):
    """Connect oi-sim to the gateway stack."""
    sim = OiSim(
        gateway=f"ws://localhost:{gateway_stack['server'].port}/datp",
        device_id="test-e2e-sim",
    )
    await sim.connect()
    await asyncio.sleep(0.3)  # allow registration
    yield sim
    await sim.disconnect()


class TestFullFlow:
    """End-to-end tests connecting all components."""

    @pytest.mark.asyncio
    async def test_audio_upload_triggers_stt_and_channel(self, gateway_stack, sim_device):
        """Test: audio upload → STT → channel → pi backend called."""
        sim = sim_device
        pi_backend = gateway_stack["pi_backend"]

        # Upload audio (simulates long-hold → record → release)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(b"\x00" * 2048)
            tmp_path = tmp.name

        try:
            stream_id = await sim.upload_audio_file(tmp_path)
            assert stream_id.startswith("rec_")
        finally:
            import os
            os.unlink(tmp_path)

        # Wait for pipeline to process
        # 1. Audio buffering (async)
        # 2. recording_finished triggers transcription
        # 3. Transcript → channel service → pi backend
        await asyncio.sleep(0.5)

        # Verify pi backend was called with transcript
        assert pi_backend.call_count >= 1
        assert "transcribed text" in pi_backend.last_message

    @pytest.mark.asyncio
    async def test_agent_response_triggers_tts_delivery(self, gateway_stack, sim_device):
        """Test: pi response → TTS → audio cache on device."""
        sim = sim_device
        dispatcher = gateway_stack["dispatcher"]

        # Move to THINKING so agent_response can trigger RESPONSE_CACHED.
        # In the real flow, audio upload transitions READY → RECORDING → UPLOADING → THINKING.
        # The agent_response arrives while in THINKING state.
        sim._state_machine._state = State.THINKING

        # Simulate receiving a pi response
        gateway_stack["server"].event_bus.emit("agent_response", "test-e2e-sim", {
            "stream_id": "rec_test",
            "transcript": "test command",
            "response_text": "Agent response text",
            "device_context": {
                "source_device": "test-e2e-sim",
                "foreground": "test-e2e-sim",
                "online": ["test-e2e-sim"],
                "capabilities": {"test-e2e-sim": {}}
            }
        })

        # Wait for delivery pipeline to process
        await asyncio.sleep(0.3)

        # Verify audio cache commands were sent
        sim.assert_command_received("audio.cache.put_begin")
        # Verify chunks were sent
        assert sim._state_machine._cache_chunk_count > 0
        sim.assert_command_received("audio.cache.put_end")

        # Verify device is in RESPONSE_CACHED state
        assert sim.state == State.RESPONSE_CACHED

    @pytest.mark.asyncio
    async def test_audio_playback_transitions_state(self, gateway_stack, sim_device):
        """Test: audio.play command transitions device to PLAYING state."""
        sim = sim_device
        dispatcher = gateway_stack["dispatcher"]
        
        # Move sim to RESPONSE_CACHED first (simulate having cached audio)
        sim._state_machine._state = State.RESPONSE_CACHED
        
        # Send audio.play command
        ok = await dispatcher.audio_play("test-e2e-sim")
        assert ok is True
        
        # Verify device transitions to PLAYING
        assert sim.state == State.PLAYING

    @pytest.mark.asyncio
    async def test_mute_command_transitions_state(self, gateway_stack, sim_device):
        """Test: device.mute_until command transitions device to MUTED state."""
        sim = sim_device
        dispatcher = gateway_stack["dispatcher"]
        
        # Verify initial state
        assert sim.state == State.READY
        
        # Send mute command (30 minutes from now)
        from datetime import datetime, timedelta, timezone
        mute_until = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        ok = await dispatcher.mute_until("test-e2e-sim", until=mute_until)
        assert ok is True
        
        # Verify device transitions to MUTED state
        assert sim.state == State.MUTED
        assert sim.muted_until is not None


class TestComponentIntegration:
    """Tests for individual component integration points."""

    @pytest.mark.asyncio
    async def test_stt_pipeline_emits_transcript_event(self, gateway_stack, sim_device):
        """Verify STT pipeline emits transcript event after recording_finished."""
        sim = sim_device
        transcript_received = None
        
        def capture_transcript(event_type, device_id, payload):
            nonlocal transcript_received
            if event_type == "transcript":
                transcript_received = payload
        
        gateway_stack["server"].event_bus.subscribe(capture_transcript)
        
        # Upload audio
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(b"\x00" * 2048)
            tmp_path = tmp.name
        
        try:
            await sim.upload_audio_file(tmp_path)
        finally:
            import os
            os.unlink(tmp_path)
        
        # Wait for STT pipeline
        await asyncio.sleep(0.3)
        
        # Verify transcript event was emitted
        assert transcript_received is not None
        assert "text" in transcript_received

    @pytest.mark.asyncio
    async def test_channel_service_emits_agent_response(self, gateway_stack, sim_device):
        """Verify channel service emits agent_response event after transcript."""
        sim = sim_device
        response_received = None
        
        def capture_response(event_type, device_id, payload):
            nonlocal response_received
            if event_type == "agent_response":
                response_received = payload
        
        gateway_stack["server"].event_bus.subscribe(capture_response)
        
        # Upload audio (triggers transcript → pi → response)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(b"\x00" * 2048)
            tmp_path = tmp.name
        
        try:
            await sim.upload_audio_file(tmp_path)
        finally:
            import os
            os.unlink(tmp_path)
        
        # Wait for full channel flow
        await asyncio.sleep(0.5)
        
        # Verify agent_response was emitted
        assert response_received is not None
        assert "response_text" in response_received

    @pytest.mark.asyncio
    async def test_delivery_pipeline_emits_audio_delivered(self, gateway_stack, sim_device):
        """Verify audio delivery pipeline emits audio_delivered event."""
        sim = sim_device
        audio_delivered = None
        
        def capture_delivered(event_type, device_id, payload):
            nonlocal audio_delivered
            if event_type == "audio_delivered":
                audio_delivered = payload
        
        gateway_stack["server"].event_bus.subscribe(capture_delivered)
        
        # Send agent_response with text
        gateway_stack["server"].event_bus.emit("agent_response", "test-e2e-sim", {
            "stream_id": "rec_test",
            "transcript": "test",
            "response_text": "Test response",
            "device_context": {
                "source_device": "test-e2e-sim",
                "foreground": "test-e2e-sim",
                "online": ["test-e2e-sim"],
                "capabilities": {}
            }
        })
        
        # Wait for delivery
        await asyncio.sleep(0.3)
        
        # Verify audio_delivered was emitted
        assert audio_delivered is not None
        assert "response_id" in audio_delivered
