from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from audio.delivery import AudioDeliveryPipeline, ResponseTextSegmenter
from datp import EventBus


class DispatcherStub:
    def __init__(self):
        self.cache_put_begin = AsyncMock(return_value=True)
        self.cache_put_chunk = AsyncMock(return_value=True)
        self.cache_put_end = AsyncMock(return_value=True)


class RecordingStreamingTts:
    def __init__(self):
        self.texts: list[str] = []

    def synthesize_pcm_stream(self, text, chunk_size):
        self.texts.append(text)
        return iter([f"pcm:{text}".encode()])


def test_response_text_segmenter_flushes_stable_speech_units() -> None:
    segmenter = ResponseTextSegmenter(min_chars=12, max_buffer_chars=30)

    assert segmenter.push("Hello there") == []
    assert segmenter.push(". How are") == ["Hello there."]
    assert segmenter.push(" you doing today without punctuation") == ["How are you doing today"]
    assert segmenter.flush() == "without punctuation"


def test_response_text_segmenter_avoids_tiny_comma_fragments() -> None:
    segmenter = ResponseTextSegmenter(min_chars=16)

    assert segmenter.push("Yes, ") == []
    assert segmenter.push("that works, next") == ["Yes, that works,"]
    assert segmenter.flush() == "next"


@pytest.mark.asyncio
async def test_audio_delivery_speaks_agent_stream_deltas_by_sentence() -> None:
    event_bus = EventBus()
    dispatcher = DispatcherStub()
    tts = RecordingStreamingTts()
    AudioDeliveryPipeline(event_bus, dispatcher, tts, min_stream_segment_chars=8)

    delivered = []
    event_bus.subscribe(lambda event_type, device_id, payload: delivered.append((event_type, device_id, payload)))

    with patch("audio.delivery.generate_response_id", side_effect=["resp-1", "resp-2"]):
        event_bus.emit("agent_response_stream", "dev1", {"text_delta": "Hello world. Still", "is_final": False, "stream_id": "s1"})
        await asyncio.sleep(0.05)
        event_bus.emit("agent_response_stream", "dev1", {"text_delta": " here", "is_final": True, "stream_id": "s1"})
        await asyncio.sleep(0.05)

    assert tts.texts == ["Hello world.", "Still here"]
    assert dispatcher.cache_put_begin.await_count == 2
    assert dispatcher.cache_put_chunk.await_count == 2
    assert dispatcher.cache_put_end.await_count == 2
    assert [payload["response_text"] for event, _, payload in delivered if event == "audio_delivered"] == ["Hello world.", "Still here"]


@pytest.mark.asyncio
async def test_streaming_agent_final_response_is_not_spoken_twice() -> None:
    event_bus = EventBus()
    dispatcher = DispatcherStub()
    tts = RecordingStreamingTts()
    pipeline = AudioDeliveryPipeline(event_bus, dispatcher, tts)

    event_bus.emit("agent_response", "dev1", {"response_text": "already streamed", "streaming_used": True})
    await asyncio.sleep(0.05)

    assert tts.texts == []
    assert dispatcher.cache_put_begin.await_count == 0

    await pipeline._do_deliver_audio("dev1", {"streaming_used": False}, "non-streaming")
    assert tts.texts == ["non-streaming"]
