from __future__ import annotations

from typing import Any, Protocol


class Transport(Protocol):
    def get(self, path: str) -> dict[str, Any]: ...
    def post(self, path: str, data: dict[str, Any]) -> dict[str, Any]: ...


class GatewayAPI:
    """Gateway-facing module for oi device and route operations."""

    def __init__(self, transport: Transport) -> None:
        self.transport = transport

    def list_devices(self) -> dict[str, Any]:
        return self.transport.get("/api/devices")

    def gateway_status(self) -> dict[str, Any]:
        return self.transport.get("/api/health")

    def send_device_command(self, device_id: str, command_name: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.transport.post(f"/api/devices/{device_id}/commands/{command_name}", body)

    def show_status(self, device_id: str, state: str, label: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {"state": state}
        if label is not None:
            body["label"] = label
        return self.send_device_command(device_id, "show_status", body)

    def mute_until(self, device_id: str, minutes: int) -> dict[str, Any]:
        return self.send_device_command(device_id, "mute_until", {"minutes": minutes})

    def route_text(self, device_id: str, text: str) -> dict[str, Any]:
        return self.transport.post("/api/route", {"device_id": device_id, "text": text})

    def audio_play(self, device_id: str, response_id: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if response_id is not None:
            body["response_id"] = response_id
        return self.send_device_command(device_id, "audio_play", body)
