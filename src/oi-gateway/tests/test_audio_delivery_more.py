from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from audio.delivery import AudioDeliveryPipeline
from audio.tts import StubTtsBackend
from datp import EventBus


class DispatcherStub:
    def __init__(self):
        self.cache_put_begin = AsyncMock(return_value=True)
        self.cache_put_chunk = AsyncMock(return_value=True)
        self.cache_put_end = AsyncMock(return_value=True)


class StreamingTts:
    def __init__(self, chunks):
        self._chunks = chunks

    def synthesize_pcm_stream(self, text, chunk_size):
        return iter(self._chunks)


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def dispatcher():
    return DispatcherStub()


def test_on_event_handles_missing_or_stopped_loop(event_bus, dispatcher, caplog):
    pipeline = AudioDeliveryPipeline(event_bus, dispatcher, StubTtsBackend())

    caplog.set_level("WARNING")
    with patch("audio.delivery.asyncio.get_running_loop", side_effect=RuntimeError):
        pipeline._on_event("agent_response", "dev1", {"response_text": "Hello"})
    assert "No event loop running" in caplog.text

    class FakeLoop:
        def is_running(self):
            return False

    with patch("audio.delivery.asyncio.get_running_loop", return_value=FakeLoop()), patch("audio.delivery.asyncio.ensure_future") as ensure_future:
        pipeline._on_event("agent_response", "dev1", {"response_text": "Hello"})
        ensure_future.assert_not_called()
    assert "Event loop not running" in caplog.text


@pytest.mark.asyncio
async def test_streaming_delivery_success_and_failures(event_bus, dispatcher):
    pipeline = AudioDeliveryPipeline(event_bus, dispatcher, StreamingTts([b"aa", b"bb"]))
    delivered = []
    event_bus.subscribe(lambda event_type, device_id, payload: delivered.append((event_type, device_id, payload)))

    with patch("audio.delivery.generate_response_id", return_value="resp-stream"):
        await pipeline._do_deliver_audio("dev1", {"stream_id": "s1"}, "hello")

    assert dispatcher.cache_put_begin.await_count == 1
    assert dispatcher.cache_put_chunk.await_count == 2
    assert dispatcher.cache_put_end.await_count == 1
    assert any(event_type == "audio_delivered" for event_type, _, _ in delivered)

    dispatcher = DispatcherStub()
    dispatcher.cache_put_chunk = AsyncMock(side_effect=[True, False])
    pipeline = AudioDeliveryPipeline(event_bus, dispatcher, StreamingTts([b"aa", b"bb"]))
    with patch("audio.delivery.generate_response_id", return_value="resp-stream-fail"):
        await pipeline._do_deliver_audio("dev1", {}, "hello")
    assert dispatcher.cache_put_end.await_count == 0

    class BrokenStreamingTts:
        def synthesize_pcm_stream(self, text, chunk_size):
            raise RuntimeError("boom")

    dispatcher = DispatcherStub()
    pipeline = AudioDeliveryPipeline(event_bus, dispatcher, BrokenStreamingTts())
    await pipeline._do_deliver_audio("dev1", {}, "hello")
    assert dispatcher.cache_put_chunk.await_count == 0


@pytest.mark.asyncio
async def test_wav_delivery_edge_cases_and_end_failure(event_bus, dispatcher):
    backend = StubTtsBackend()
    backend.synthesize = lambda _text: b""
    pipeline = AudioDeliveryPipeline(event_bus, dispatcher, backend)
    await pipeline._do_deliver_audio("dev1", {}, "hello")
    assert dispatcher.cache_put_chunk.await_count == 0

    backend = StubTtsBackend(response_wav=b"RIFFbad")
    dispatcher = DispatcherStub()
    pipeline = AudioDeliveryPipeline(event_bus, dispatcher, backend)
    with patch("audio.delivery._wav_to_pcm_chunks", return_value=[]):
        await pipeline._do_deliver_audio("dev1", {}, "hello")
    assert dispatcher.cache_put_chunk.await_count == 0

    backend = StubTtsBackend()
    dispatcher = DispatcherStub()
    dispatcher.cache_put_end = AsyncMock(return_value=False)
    pipeline = AudioDeliveryPipeline(event_bus, dispatcher, backend)
    delivered = []
    event_bus.subscribe(lambda event_type, device_id, payload: delivered.append(event_type))
    await pipeline._do_deliver_audio("dev1", {}, "hello")
    assert "audio_delivered" not in delivered

    def bad_synthesize(_text):
        raise RuntimeError("bad synth")

    backend.synthesize = bad_synthesize
    dispatcher = DispatcherStub()
    pipeline = AudioDeliveryPipeline(event_bus, dispatcher, backend)
    await pipeline._do_deliver_audio("dev1", {}, "hello")
    assert dispatcher.cache_put_chunk.await_count == 0


@pytest.mark.asyncio
async def test_deliver_audio_reuses_per_device_lock(event_bus, dispatcher):
    pipeline = AudioDeliveryPipeline(event_bus, dispatcher, StubTtsBackend())
    calls = []

    async def fake_do(device_id, payload, response_text):
        calls.append((device_id, response_text, id(pipeline._device_locks[device_id])))

    pipeline._do_deliver_audio = fake_do

    await asyncio.gather(
        pipeline._deliver_audio("dev1", {}, "one"),
        pipeline._deliver_audio("dev1", {}, "two"),
    )

    assert len(pipeline._device_locks) == 1
    assert calls[0][2] == calls[1][2]
