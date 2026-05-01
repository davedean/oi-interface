from __future__ import annotations

import base64

import pytest

from audio.pipeline import StreamAccumulator, pcm16_to_mono
from datp import EventBus


class CapturingStt:
    def __init__(self):
        self.calls = []

    def transcribe(self, pcm: bytes, sample_rate: int):
        self.calls.append((pcm, sample_rate))
        return "ok", None


def test_pcm16_to_mono_takes_first_channel_and_drops_partial_frames() -> None:
    # stereo frames: L1 R1 L2 R2, plus an incomplete byte that must be ignored
    stereo = b"\x01\x00\x02\x00\x03\x00\x04\x00\xff"
    assert pcm16_to_mono(stereo, channels=2) == b"\x01\x00\x03\x00"
    assert pcm16_to_mono(b"abc", channels=2) == b""
    assert pcm16_to_mono(b"mono", channels=1) == b"mono"


@pytest.mark.asyncio
async def test_stream_accumulator_normalizes_stereo_chunks_before_stt() -> None:
    event_bus = EventBus()
    stt = CapturingStt()
    StreamAccumulator(event_bus, stt)
    seen = []
    event_bus.subscribe(lambda event_type, _device_id, payload: seen.append((event_type, payload)))

    stereo = b"\x01\x00\x02\x00\x03\x00\x04\x00"
    event_bus.emit("audio_chunk", "dev1", {
        "stream_id": "s1",
        "seq": 0,
        "sample_rate": 44100,
        "channels": 2,
        "data_b64": base64.b64encode(stereo).decode(),
    })
    event_bus.emit("event", "dev1", {"event": "audio.recording_finished", "stream_id": "s1"})

    import asyncio
    await asyncio.sleep(0.05)

    assert stt.calls == [(b"\x01\x00\x03\x00", 44100)]
    transcript = [payload for event_type, payload in seen if event_type == "transcript"][0]
    assert transcript["audio_metrics"]["sample_rate"] == 44100
    assert transcript["audio_metrics"]["channels"] == 2
    chunk_event = [payload for event_type, payload in seen if event_type == "audio_stream_chunk_received"][0]
    assert chunk_event["channels"] == 2
    assert chunk_event["bytes"] == 4
