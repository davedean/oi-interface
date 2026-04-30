"""Unit tests for the dashboard gateway poller."""
from __future__ import annotations

from oi_dashboard.poller import DashboardPoller
from oi_dashboard.state import DashboardState


class FakeGatewayApi:
    def __init__(self, responses: list[tuple[int, dict[str, object]]]) -> None:
        self._responses = responses

    async def get_devices(self) -> tuple[int, dict[str, object]]:
        return self._responses.pop(0)


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
