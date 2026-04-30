from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from audio.pipeline import AudioStream, StreamAccumulator
from audio.stt import StubSttBackend
from datp import EventBus


@pytest.fixture
def event_bus():
    return EventBus()


def test_audio_stream_reassemble_with_gaps_logs_warning(caplog):
    stream = AudioStream(device_id="dev1", stream_id="s1")
    stream.chunks[1] = b"bbb"
    caplog.set_level("WARNING")
    assert stream.reassemble_pcm() == b"bbb"
    assert "not complete" in caplog.text


def test_stream_accumulator_on_event_handles_non_running_loop_and_invalid_chunk(event_bus, caplog):
    accum = StreamAccumulator(event_bus, StubSttBackend())
    caplog.set_level("WARNING")

    event_bus.emit("audio_chunk", "dev1", {"stream_id": "", "seq": -1, "data_b64": ""})
    assert "Invalid audio chunk" in caplog.text

    class FakeLoop:
        def is_running(self):
            return False

    with patch("audio.pipeline.asyncio.get_event_loop", return_value=FakeLoop()), patch("audio.pipeline.asyncio.ensure_future") as ensure_future:
        event_bus.emit("event", "dev1", {"event": "audio.recording_finished", "stream_id": "s1"})
        ensure_future.assert_not_called()
    assert "Event loop not running" in caplog.text


def test_stream_accumulator_buffer_chunk_decode_failure(event_bus, caplog):
    accum = StreamAccumulator(event_bus, StubSttBackend())
    caplog.set_level("WARNING")
    accum._buffer_chunk("dev1", {"stream_id": "s1", "seq": 0, "data_b64": "a", "sample_rate": 16000})
    assert "Failed to decode audio chunk" in caplog.text


@pytest.mark.asyncio
async def test_transcribe_missing_stream_empty_audio_and_exception(event_bus, caplog):
    backend = StubSttBackend()
    accum = StreamAccumulator(event_bus, backend)

    caplog.set_level("WARNING")
    await accum._transcribe("dev1", "missing")
    assert "not found for transcription" in caplog.text

    accum._streams["s1"] = AudioStream(device_id="dev1", stream_id="s1")
    await accum._transcribe("dev1", "s1")
    assert "has no audio data" in caplog.text

    class BrokenStt:
        def transcribe(self, pcm_bytes, sample_rate):
            raise RuntimeError("boom")

    accum = StreamAccumulator(event_bus, BrokenStt())
    accum._streams["s2"] = AudioStream(device_id="dev1", stream_id="s2")
    accum._streams["s2"].chunks[0] = b"abc"
    caplog.set_level("ERROR")
    await accum._transcribe("dev1", "s2")
    assert "STT transcription failed for stream s2" in caplog.text


@pytest.mark.asyncio
async def test_transcribe_logs_metrics_and_emits_transcript(event_bus, caplog):
    transcript_events = []
    event_bus.subscribe(lambda event_type, device_id, payload: transcript_events.append((event_type, payload)))

    class MetricsStt:
        def transcribe(self, pcm_bytes, sample_rate):
            metrics = SimpleNamespace(duration_seconds=1.2, word_count=3, inference_time_ms=12.0)
            return "hello there", metrics

    accum = StreamAccumulator(event_bus, MetricsStt())
    accum._streams["s3"] = AudioStream(device_id="dev1", stream_id="s3")
    accum._streams["s3"].chunks[0] = base64.b64decode(base64.b64encode(b"abc"))

    caplog.set_level("DEBUG")
    await accum._transcribe("dev1", "s3")

    assert any(event_type == "transcript" for event_type, _ in transcript_events)
    assert "STT metrics for stream s3" in caplog.text


@pytest.mark.asyncio
async def test_transcribe_accepts_legacy_string_result(event_bus):
    captured = []
    event_bus.subscribe(lambda event_type, device_id, payload: captured.append((event_type, payload)))

    class LegacyStt:
        def transcribe(self, pcm_bytes, sample_rate):
            return "legacy transcript"

    accum = StreamAccumulator(event_bus, LegacyStt())
    accum._streams["legacy"] = AudioStream(device_id="dev1", stream_id="legacy")
    accum._streams["legacy"].chunks[0] = b"abc"
    await accum._transcribe("dev1", "legacy")

    transcript_payloads = [payload for event_type, payload in captured if event_type == "transcript"]
    assert transcript_payloads[0]["text"] == "legacy transcript"
    assert transcript_payloads[0]["cleaned"] == "legacy transcript."
