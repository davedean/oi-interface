from __future__ import annotations

import base64

import pytest

from audio.pipeline import StreamAccumulator
from datp import EventBus


class HookedStreamingStt:
    def __init__(self):
        self.accepted = []
        self.finished = []

    def accept_audio_chunk(self, stream_id: str, pcm: bytes, sample_rate: int, seq: int):
        self.accepted.append((stream_id, pcm, sample_rate, seq))
        if seq == 1:
            return "partial words"
        return ""

    def finish_stream(self, stream_id: str, pcm: bytes, sample_rate: int):
        self.finished.append((stream_id, pcm, sample_rate))
        return "final words", {"backend": "hooked"}


class BatchStt:
    def __init__(self):
        self.calls = []

    def transcribe(self, pcm: bytes, sample_rate: int):
        self.calls.append((pcm, sample_rate))
        return "batch final", None


@pytest.mark.asyncio
async def test_streaming_stt_hooks_emit_partial_and_final_with_metrics() -> None:
    event_bus = EventBus()
    stt = HookedStreamingStt()
    StreamAccumulator(event_bus, stt)
    seen = []
    event_bus.subscribe(lambda event_type, device_id, payload: seen.append((event_type, device_id, payload)))

    event_bus.emit("audio_chunk", "dev1", {"stream_id": "s1", "seq": 0, "sample_rate": 16000, "data_b64": base64.b64encode(b"aa").decode()})
    event_bus.emit("audio_chunk", "dev1", {"stream_id": "s1", "seq": 1, "sample_rate": 16000, "data_b64": base64.b64encode(b"bb").decode()})
    event_bus.emit("event", "dev1", {"event": "audio.recording_finished", "stream_id": "s1", "duration_ms": 250})

    import asyncio
    await asyncio.sleep(0.05)

    assert stt.accepted == [("s1", b"aa", 16000, 0), ("s1", b"bb", 16000, 1)]
    assert stt.finished == [("s1", b"aabb", 16000)]
    partials = [payload for event, _, payload in seen if event == "transcript_partial"]
    finals = [payload for event, _, payload in seen if event == "transcript"]
    assert partials == [{"stream_id": "s1", "text": "partial words", "cleaned": "partial words.", "seq": 1}]
    assert finals[0]["cleaned"] == "final words."
    assert finals[0]["audio_metrics"]["chunk_count"] == 2
    assert finals[0]["audio_metrics"]["byte_count"] == 4
    assert finals[0]["audio_metrics"]["duration_ms"] == 250


@pytest.mark.asyncio
async def test_batch_stt_still_transcribes_already_uploaded_audio_on_finish() -> None:
    event_bus = EventBus()
    stt = BatchStt()
    StreamAccumulator(event_bus, stt)
    seen = []
    event_bus.subscribe(lambda event_type, device_id, payload: seen.append((event_type, payload)))

    event_bus.emit("audio_chunk", "dev1", {"stream_id": "s2", "seq": 0, "sample_rate": 8000, "data_b64": base64.b64encode(b"chunk").decode()})
    event_bus.emit("event", "dev1", {"event": "audio.recording_finished", "stream_id": "s2"})

    import asyncio
    await asyncio.sleep(0.05)

    assert stt.calls == [(b"chunk", 8000)]
    assert any(event == "transcript" and payload["cleaned"] == "batch final." for event, payload in seen)
