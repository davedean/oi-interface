from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from datp.events import EventBus
from text.delivery import TextDeliveryPipeline


class ProgressDispatcher:
    def __init__(self):
        self.progress_calls = []
        self.response_calls = []

    async def show_progress(self, device_id, text, kind, seq):
        self.progress_calls.append((device_id, text, kind, seq))
        return True

    async def show_response_delta(self, device_id, text_delta, is_final, seq):
        self.response_calls.append((device_id, text_delta, is_final, seq))
        return True


@pytest.fixture
def event_bus():
    return EventBus()


def test_text_delivery_handles_missing_or_stopped_loop(event_bus, caplog):
    dispatcher = ProgressDispatcher()
    pipeline = TextDeliveryPipeline(event_bus, dispatcher)

    caplog.set_level("WARNING")
    with patch("text.delivery.asyncio.get_running_loop", side_effect=RuntimeError):
        pipeline._on_event("agent_progress", "dev1", {"text": "working"})
    assert "No event loop running" in caplog.text

    class FakeLoop:
        def is_running(self):
            return False

    with patch("text.delivery.asyncio.get_running_loop", return_value=FakeLoop()):
        pipeline._on_event("agent_progress", "dev1", {"text": "working"})
    assert "Event loop not running" in caplog.text


@pytest.mark.asyncio
async def test_text_delivery_progress_fallback_and_sequence_reset(event_bus):
    dispatcher = ProgressDispatcher()
    pipeline = TextDeliveryPipeline(event_bus, dispatcher)

    event_bus.emit("agent_progress", "dev1", {"text": "thinking", "kind": "tool"})
    event_bus.emit("agent_response_stream", "dev1", {"text_delta": "Hello", "is_final": False})
    event_bus.emit("agent_response_stream", "dev1", {"text_delta": " world", "is_final": True, "correlation_id": "c1"})
    await asyncio.sleep(0.05)

    assert dispatcher.progress_calls == [("dev1", "thinking", "tool", 0)]
    assert dispatcher.response_calls[0] == ("dev1", "Hello", False, 1)
    assert dispatcher.response_calls[1] == ("dev1", " world", True, 2)

    event_bus.emit("agent_response_delta", "dev1", {"text_delta": "reset", "is_final": False})
    await asyncio.sleep(0.05)
    assert dispatcher.response_calls[-1] == ("dev1", "reset", False, 0)


@pytest.mark.asyncio
async def test_text_delivery_reuses_device_lock(event_bus):
    dispatcher = ProgressDispatcher()
    pipeline = TextDeliveryPipeline(event_bus, dispatcher)
    calls = []

    async def fake_do(event_type, device_id, payload):
        calls.append((event_type, id(pipeline._device_locks[device_id])))

    pipeline._do_deliver_text_delta = fake_do
    await asyncio.gather(
        pipeline._deliver_text_delta("agent_progress", "dev1", {"text": "a"}),
        pipeline._deliver_text_delta("agent_progress", "dev1", {"text": "b"}),
    )
    assert len(pipeline._device_locks) == 1
    assert calls[0][1] == calls[1][1]
