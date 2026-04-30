"""Unit tests for the dashboard gateway poller."""
from __future__ import annotations

from oi_dashboard.poller import DashboardPoller
from oi_dashboard.state import DashboardState


class FakeGatewayApi:
    def __init__(
        self,
        device_responses: list[tuple[int, dict[str, object]]],
        transcript_responses: list[tuple[int, dict[str, object]]] | None = None,
    ) -> None:
        self._device_responses = device_responses
        self._transcript_responses = transcript_responses or [(200, {"transcripts": []}) for _ in device_responses]

    async def get_devices(self) -> tuple[int, dict[str, object]]:
        return self._device_responses.pop(0)

    async def get_transcripts(self) -> tuple[int, dict[str, object]]:
        return self._transcript_responses.pop(0)


async def test_poll_once_emits_online_and_offline_transitions() -> None:
    state = DashboardState()
    api = FakeGatewayApi([
        (200, {"devices": [{"device_id": "device-1", "online": True}]}),
        (200, {"devices": []}),
    ])
    poller = DashboardPoller(api, state)

    first_events = await poller.poll_once()
    second_events = await poller.poll_once()

    assert first_events == [("device_online", {"device_id": "device-1", "online": True})]
    assert second_events == [("device_offline", {"device_id": "device-1"})]
    assert state.devices["device-1"].online is False


async def test_poll_once_ignores_non_200_responses() -> None:
    state = DashboardState()
    api = FakeGatewayApi([(503, {"error": "unavailable"})])
    poller = DashboardPoller(api, state)

    assert await poller.poll_once() == []
    assert state.devices == {}


async def test_poll_once_emits_transcript_and_agent_response_events() -> None:
    state = DashboardState()
    api = FakeGatewayApi(
        [(200, {"devices": [{"device_id": "device-1", "online": True}]})],
        [(200, {"transcripts": [{
            "device_id": "device-1",
            "transcript": "Hello there",
            "response": "Hi!",
            "stream_id": "stream-1",
            "conversation_id": "stream-1",
        }]})],
    )
    poller = DashboardPoller(api, state)

    events = await poller.poll_once()

    assert events[0] == ("device_online", {"device_id": "device-1", "online": True})
    assert events[1][0] == "transcript"
    assert events[1][1]["device_id"] == "device-1"
    assert events[1][1]["transcript"] == "Hello there"
    assert events[1][1]["stream_id"] == "stream-1"
    assert events[1][1]["conversation_id"] == "stream-1"
    assert "timestamp" in events[1][1]
    assert events[2] == ("agent_response", {
        "timestamp": state.transcripts[0].timestamp,
        "device_id": "device-1",
        "transcript": "Hello there",
        "response": "Hi!",
        "stream_id": "stream-1",
        "conversation_id": "stream-1",
    })
    assert state.transcripts[0].response == "Hi!"
