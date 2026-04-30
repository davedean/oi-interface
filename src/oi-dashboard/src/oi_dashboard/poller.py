"""Gateway polling adapter for keeping the dashboard projection in sync."""
from __future__ import annotations

from typing import Any, Protocol

from .state import DashboardState


class DeviceProjectionSource(Protocol):
    """Protocol for adapters that can fetch the gateway projections."""

    async def get_devices(self) -> tuple[int, dict[str, Any]]: ...
    async def get_transcripts(self) -> tuple[int, dict[str, Any]]: ...


class DashboardPoller:
    """Sync the dashboard projection from the gateway device projection."""

    def __init__(self, gateway_api: DeviceProjectionSource, state: DashboardState) -> None:
        self._gateway_api = gateway_api
        self._state = state

    async def poll_once(self) -> list[tuple[str, dict[str, Any]]]:
        """Fetch the current gateway projections and return state transition events."""
        device_status, device_data = await self._gateway_api.get_devices()
        if device_status != 200:
            return []

        events: list[tuple[str, dict[str, Any]]] = []
        devices = device_data.get("devices", [])
        current_ids: set[str] = set()
        for device_info in devices:
            device_id = device_info.get("device_id", "")
            if not device_id:
                continue
            current_ids.add(device_id)
            transition = self._state.apply_polled_device(device_id, device_info)
            if transition is not None:
                events.append(transition)

        events.extend(self._state.mark_missing_devices_offline(current_ids))

        transcript_status, transcript_data = await self._gateway_api.get_transcripts()
        if transcript_status == 200:
            events.extend(self._state.apply_polled_transcripts(transcript_data.get("transcripts", [])))

        return events
