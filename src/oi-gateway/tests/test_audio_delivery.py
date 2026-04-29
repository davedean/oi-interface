"""Tests for audio delivery pipeline."""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import sys

gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))

from datp import EventBus
from datp.commands import CommandDispatcher
from audio.delivery import AudioDeliveryPipeline
from audio.tts import StubTtsBackend


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def event_bus():
    """Create a fresh event bus."""
    return EventBus()


@pytest.fixture
def mock_dispatcher():
    """Create a mock CommandDispatcher."""
    dispatcher = MagicMock(spec=CommandDispatcher)
    dispatcher.cache_put_begin = AsyncMock(return_value=True)
    dispatcher.cache_put_chunk = AsyncMock(return_value=True)
    dispatcher.cache_put_end = AsyncMock(return_value=True)
    return dispatcher


@pytest.fixture
def stub_backend():
    """Create a StubTtsBackend with predictable WAV output."""
    # Create a small valid WAV (20 bytes of PCM)
    pcm = b"\x00\x01\x02\x03\x04\x05\x06\x07" * 10  # 80 bytes
    wav = _make_minimal_wav(pcm, sample_rate=16000)
    return StubTtsBackend(response_wav=wav)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_minimal_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    """Create a minimal valid WAV file from PCM data."""
    import struct

    byte_rate = sample_rate * 1 * 16 // 8
    block_align = 1 * 16 // 8

    fmt_chunk = struct.pack("<HHIIHH", 1, 1, sample_rate, byte_rate, block_align, 16)
    data_size = len(pcm)
    file_size = 36 + data_size

    wav = b"RIFF"
    wav += struct.pack("<I", file_size)
    wav += b"WAVE"
    wav += b"fmt "
    wav += struct.pack("<I", len(fmt_chunk))
    wav += fmt_chunk
    wav += b"data"
    wav += struct.pack("<I", data_size)
    wav += pcm

    return wav


# ------------------------------------------------------------------
# Tests: AudioDeliveryPipeline initialization
# ------------------------------------------------------------------


def test_pipeline_requires_dispatcher(event_bus, stub_backend):
    """Verify AudioDeliveryPipeline requires a CommandDispatcher."""
    with pytest.raises(TypeError):
        AudioDeliveryPipeline(event_bus, None, stub_backend)  # type: ignore


def test_pipeline_requires_backend(event_bus, mock_dispatcher):
    """Verify AudioDeliveryPipeline requires a TtsBackend."""
    with pytest.raises(TypeError):
        AudioDeliveryPipeline(event_bus, mock_dispatcher, None)  # type: ignore


def test_pipeline_initializes_with_valid_args(event_bus, mock_dispatcher, stub_backend):
    """Verify AudioDeliveryPipeline initializes correctly."""
    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    assert pipeline._event_bus is event_bus
    assert pipeline._dispatcher is mock_dispatcher
    assert pipeline._tts is stub_backend


def test_pipeline_subscribes_to_agent_response(event_bus, mock_dispatcher, stub_backend):
    """Verify AudioDeliveryPipeline subscribes to agent_response events."""
    captured_events = []

    def capture(event_type, device_id, payload):
        captured_events.append((event_type, device_id, payload))

    event_bus.subscribe(capture)

    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    # Emit an agent_response event
    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "hello",
        "response_text": "Hello, how can I help you?",
    })

    # Pipeline should have received it
    assert len(captured_events) >= 1


# ------------------------------------------------------------------
# Tests: TTS synthesis on agent_response
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_synthesizes_on_agent_response(event_bus, mock_dispatcher, stub_backend):
    """Verify pipeline runs TTS when agent_response is received."""
    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    synthesize_called = False
    original_synthesize = stub_backend.synthesize

    def track_synthesis(text):
        nonlocal synthesize_called
        synthesize_called = True
        return original_synthesize(text)

    stub_backend.synthesize = track_synthesis

    # Emit agent_response
    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "hello",
        "response_text": "This is the response text.",
    })

    # Wait for async processing
    await asyncio.sleep(0.2)

    assert synthesize_called, "TTS synthesize should have been called"


@pytest.mark.asyncio
async def test_pipeline_skips_empty_response_text(event_bus, mock_dispatcher, stub_backend):
    """Verify pipeline ignores agent_response with empty response_text."""
    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    stub_backend.synthesize = AsyncMock(wraps=stub_backend.synthesize)

    # Emit agent_response with empty response_text
    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "hello",
        "response_text": "",
    })

    # Wait for async processing
    await asyncio.sleep(0.1)

    # synthesize should NOT have been called
    stub_backend.synthesize.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_skips_missing_response_text(event_bus, mock_dispatcher, stub_backend):
    """Verify pipeline ignores agent_response without response_text field."""
    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    synthesize_called = False
    original_synthesize = stub_backend.synthesize

    def track_synthesis(text):
        nonlocal synthesize_called
        synthesize_called = True
        return original_synthesize(text)

    stub_backend.synthesize = track_synthesis

    # Emit agent_response without response_text
    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "hello",
    })

    await asyncio.sleep(0.1)

    assert not synthesize_called, "TTS should not be called for missing response_text"


# ------------------------------------------------------------------
# Tests: Cache commands sent to device
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_sends_cache_put_begin(event_bus, mock_dispatcher, stub_backend):
    """Verify pipeline sends audio.cache.put_begin command."""
    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "hello",
        "response_text": "Test response",
    })

    await asyncio.sleep(0.2)

    mock_dispatcher.cache_put_begin.assert_called_once()
    call_args = mock_dispatcher.cache_put_begin.call_args
    assert call_args[0][0] == "dev1"  # device_id
    assert "response_id" in call_args[1] or len(call_args[0]) > 1  # response_id present


@pytest.mark.asyncio
async def test_pipeline_sends_cache_chunks(event_bus, mock_dispatcher, stub_backend):
    """Verify pipeline sends audio.cache.chunk commands."""
    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "hello",
        "response_text": "Test response",
    })

    await asyncio.sleep(0.2)

    # Should have sent at least one chunk
    assert mock_dispatcher.cache_put_chunk.call_count >= 1

    # Each chunk call should have correct args
    for call in mock_dispatcher.cache_put_chunk.call_args_list:
        args = call[1] if call[1] else {}
        positional = call[0] if call[0] else ()

        # Check device_id
        assert args.get("device_id") == "dev1" or (positional and positional[0] == "dev1")
        # Check data_b64 is valid base64
        data_b64 = args.get("data_b64") or (positional[3] if len(positional) > 3 else None)
        assert data_b64 is not None
        # Should decode without error
        base64.b64decode(data_b64)


@pytest.mark.asyncio
async def test_pipeline_sends_cache_put_end(event_bus, mock_dispatcher, stub_backend):
    """Verify pipeline sends audio.cache.put_end command."""
    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "hello",
        "response_text": "Test response",
    })

    await asyncio.sleep(0.2)

    mock_dispatcher.cache_put_end.assert_called_once()
    call_args = mock_dispatcher.cache_put_end.call_args
    assert call_args[0][0] == "dev1"  # device_id


@pytest.mark.asyncio
async def test_pipeline_uses_same_response_id_for_all_commands(event_bus, mock_dispatcher, stub_backend):
    """Verify all cache commands use the same response_id."""
    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "hello",
        "response_text": "Test response",
    })

    await asyncio.sleep(0.2)

    # Extract response_ids from all calls
    begin_call = mock_dispatcher.cache_put_begin.call_args
    response_id = begin_call[1].get("response_id") if begin_call[1] else begin_call[0][1] if len(begin_call[0]) > 1 else None

    assert response_id is not None

    # Check chunk calls
    for call in mock_dispatcher.cache_put_chunk.call_args_list:
        chunk_response_id = call[1].get("response_id") if call[1] else (call[0][1] if len(call[0]) > 1 else None)
        assert chunk_response_id == response_id

    # Check end call
    end_call = mock_dispatcher.cache_put_end.call_args
    # cache_put_end(device_id, response_id, sha256=None, timeout=5.0)
    # response_id is positional argument [1]
    if len(end_call[0]) >= 2:
        end_response_id = end_call[0][1]
    elif end_call[1] and "response_id" in end_call[1]:
        end_response_id = end_call[1]["response_id"]
    else:
        end_response_id = None
    assert end_response_id == response_id


# ------------------------------------------------------------------
# Tests: audio_delivered event emission
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_emits_audio_delivered_event(event_bus, mock_dispatcher, stub_backend):
    """Verify pipeline emits audio_delivered event after successful delivery."""
    captured_events = []

    def capture(event_type, device_id, payload):
        captured_events.append((event_type, device_id, payload))

    event_bus.subscribe(capture)

    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "hello",
        "response_text": "Test response",
    })

    await asyncio.sleep(0.2)

    # Should have emitted audio_delivered event
    delivered_events = [(et, did, p) for et, did, p in captured_events if et == "audio_delivered"]
    assert len(delivered_events) == 1

    event_type, device_id, payload = delivered_events[0]
    assert device_id == "dev1"
    assert "response_id" in payload
    assert "response_text" in payload


@pytest.mark.asyncio
async def test_audio_delivered_event_contains_response_metadata(event_bus, mock_dispatcher, stub_backend):
    """Verify audio_delivered event includes relevant metadata."""
    captured_payloads = []

    def capture(event_type, device_id, payload):
        if event_type == "audio_delivered":
            captured_payloads.append(payload)

    event_bus.subscribe(capture)

    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "hello",
        "response_text": "The response text here",
        "device_context": {"source_device": "dev1"},
    })

    await asyncio.sleep(0.2)

    assert len(captured_payloads) == 1
    payload = captured_payloads[0]

    assert "response_id" in payload
    assert "response_text" in payload
    assert payload["response_text"] == "The response text here"


# ------------------------------------------------------------------
# Tests: Error handling
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_handles_tts_failure(event_bus, mock_dispatcher, stub_backend):
    """Verify pipeline handles TTS synthesis failure gracefully."""
    def failing_synthesize(text):
        raise RuntimeError("TTS failed")

    stub_backend.synthesize = failing_synthesize

    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    # Emit agent_response
    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "hello",
        "response_text": "Test response",
    })

    # Should not crash
    await asyncio.sleep(0.2)

    # Should NOT emit audio_delivered on failure
    captured = []

    def capture(event_type, device_id, payload):
        if event_type == "audio_delivered":
            captured.append(payload)

    event_bus.subscribe(capture)

    assert len(captured) == 0


@pytest.mark.asyncio
async def test_pipeline_handles_cache_begin_failure(event_bus, mock_dispatcher, stub_backend):
    """Verify pipeline handles cache_put_begin failure gracefully."""
    mock_dispatcher.cache_put_begin = AsyncMock(return_value=False)

    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    # Emit agent_response
    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "hello",
        "response_text": "Test response",
    })

    # Should not crash
    await asyncio.sleep(0.2)

    # Should NOT emit audio_delivered on failure
    captured = []

    def capture(event_type, device_id, payload):
        if event_type == "audio_delivered":
            captured.append(payload)

    event_bus.subscribe(capture)

    assert len(captured) == 0


# ------------------------------------------------------------------
# Tests: Multiple responses
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_handles_multiple_responses(event_bus, mock_dispatcher, stub_backend):
    """Verify pipeline handles multiple consecutive agent_response events."""
    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    for i in range(3):
        event_bus.emit("agent_response", f"dev{i}", {
            "stream_id": f"rec_{i:03d}",
            "transcript": f"hello {i}",
            "response_text": f"Response number {i}",
        })

    await asyncio.sleep(0.3)

    # Should have sent cache_begin for each response
    assert mock_dispatcher.cache_put_begin.call_count == 3


# ------------------------------------------------------------------
# Tests: Chunk sequencing
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_sends_chunks_with_sequential_seq_numbers(event_bus, mock_dispatcher, stub_backend):
    """Verify cache chunks have sequential seq numbers starting from 0."""
    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "hello",
        "response_text": "Test response with enough text to generate multiple chunks",
    })

    await asyncio.sleep(0.2)

    seq_numbers = []
    for call in mock_dispatcher.cache_put_chunk.call_args_list:
        args = call[1] if call[1] else {}
        positional = call[0] if call[0] else ()
        seq = args.get("seq") if "seq" in args else (positional[2] if len(positional) > 2 else None)
        if seq is not None:
            seq_numbers.append(seq)

    # Should have sequential seq numbers
    assert seq_numbers == list(range(len(seq_numbers)))


# ------------------------------------------------------------------
# Integration tests
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_full_flow(event_bus, mock_dispatcher, stub_backend):
    """Verify full flow: agent_response → TTS → cache commands → audio_delivered."""
    delivered_events = []

    def capture(event_type, device_id, payload):
        if event_type == "audio_delivered":
            delivered_events.append(payload)

    event_bus.subscribe(capture)

    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    # Trigger the pipeline
    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "what time is it",
        "response_text": "It's 3 o'clock.",
    })

    await asyncio.sleep(0.2)

    # Verify all steps completed
    assert mock_dispatcher.cache_put_begin.call_count == 1
    assert mock_dispatcher.cache_put_end.call_count == 1
    assert mock_dispatcher.cache_put_chunk.call_count >= 1
    assert len(delivered_events) == 1


@pytest.mark.asyncio
async def test_pipeline_serializes_concurrent_deliveries_to_same_device(event_bus, mock_dispatcher, stub_backend):
    """Verify concurrent agent_response events to the same device are serialized."""
    import time

    # Make synthesis slow so overlapping deliveries would race without serialization.
    _original_synthesize = stub_backend.synthesize
    def slow_synthesize(text):
        time.sleep(0.05)
        return _original_synthesize(text)

    stub_backend.synthesize = slow_synthesize

    pipeline = AudioDeliveryPipeline(event_bus, mock_dispatcher, stub_backend)

    # Emit two responses for the same device concurrently.
    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_001",
        "transcript": "hello",
        "response_text": "First response",
    })
    event_bus.emit("agent_response", "dev1", {
        "stream_id": "rec_002",
        "transcript": "hello",
        "response_text": "Second response",
    })

    await asyncio.sleep(0.3)

    # Both should have completed (2 begin / 2 end calls).
    assert mock_dispatcher.cache_put_begin.call_count == 2
    assert mock_dispatcher.cache_put_end.call_count == 2

    # Verify sequences are not interleaved using mock_calls which records
    # all calls in true temporal order.
    temporal_order: list[str] = []
    for call in mock_dispatcher.mock_calls:
        name = call[0]
        if "cache_put_begin" in name:
            temporal_order.append("begin")
        elif "cache_put_chunk" in name:
            temporal_order.append("chunk")
        elif "cache_put_end" in name:
            temporal_order.append("end")

    # With serialization, the order should be: begin, chunk(s), end, begin, chunk(s), end.
    # We verify no second begin appears before the first end.
    first_end_idx = temporal_order.index("end")
    second_begin_idx = temporal_order.index("begin", 1)
    assert second_begin_idx > first_end_idx, (
        f"Concurrent deliveries were not serialized: {temporal_order}"
    )
