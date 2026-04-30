"""Dashboard projection state for devices, transcripts, and event payloads."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class DeviceState:
    """Current state for a single device."""

    device_id: str = ""
    device_type: str = ""
    session_id: str = ""
    online: bool = False
    connected_at: str | None = None
    last_seen: str | None = None
    state: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    muted_until: str | None = None
    audio_cache_bytes: int = 0


@dataclass
class TranscriptEntry:
    """A transcript/response pair."""

    timestamp: str
    device_id: str
    transcript: str
    response: str = ""
    stream_id: str = ""


class DashboardState:
    """Own the dashboard's device/transcript projection and event payloads."""

    def __init__(
        self,
        max_transcripts: int = 100,
        snapshot_transcript_limit: int = 20,
        api_transcript_limit: int = 50,
        now_factory: Callable[[], str] | None = None,
    ) -> None:
        self.max_transcripts = max_transcripts
        self.snapshot_transcript_limit = snapshot_transcript_limit
        self.api_transcript_limit = api_transcript_limit
        self.devices: dict[str, DeviceState] = {}
        self.transcripts: list[TranscriptEntry] = []
        self._now_factory = now_factory or self._utc_now_iso

    def snapshot(self) -> dict[str, Any]:
        """Return the current serialized dashboard state."""
        return {
            "devices": {
                device_id: self.device_payload(device)
                for device_id, device in self.devices.items()
            },
            "transcripts": self.transcript_payloads(self.transcripts[-self.snapshot_transcript_limit:]),
            "timestamp": self._now_factory(),
        }

    def update_device_state(self, device_id: str, info: dict[str, Any]) -> DeviceState:
        """Merge a device payload into the current projection."""
        device = self.devices.get(device_id, DeviceState(device_id=device_id))
        device.device_id = info.get("device_id", device_id)
        device.device_type = info.get("device_type", "")
        device.session_id = info.get("session_id", "")
        device.online = info.get("online", True)
        device.connected_at = info.get("connected_at")
        device.last_seen = info.get("last_seen")
        device.state = info.get("state", {})
        device.capabilities = info.get("capabilities", {})
        device.muted_until = info.get("muted_until")
        device.audio_cache_bytes = info.get("audio_cache_bytes", 0)
        self.devices[device_id] = device
        return device

    def record_device_online(self, device_id: str, info: dict[str, Any]) -> dict[str, Any]:
        """Apply a device-online event and return its broadcast payload."""
        self.update_device_state(device_id, {**info, "online": True})
        return {"device_id": device_id, **info}

    def record_device_offline(self, device_id: str) -> dict[str, Any]:
        """Apply a device-offline event and return its broadcast payload."""
        if device_id in self.devices:
            self.devices[device_id].online = False
        return {"device_id": device_id}

    def record_state_updated(self, device_id: str, state: dict[str, Any]) -> dict[str, Any]:
        """Apply a device state update and return its broadcast payload."""
        if device_id in self.devices:
            self.devices[device_id].state.update(state)
        return {"device_id": device_id, "state": state}

    def record_transcript(self, device_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Apply a transcript event and return its broadcast payload."""
        transcript = payload.get("cleaned", "") or payload.get("text", "")
        if not transcript:
            return None

        entry = TranscriptEntry(
            timestamp=self._now_factory(),
            device_id=device_id,
            transcript=transcript,
            response="",
            stream_id=payload.get("stream_id", ""),
        )
        self.transcripts.append(entry)
        overflow = len(self.transcripts) - self.max_transcripts
        if overflow > 0:
            del self.transcripts[:overflow]
        return self.timestamped_device_event(device_id, transcript=transcript)

    def record_agent_response(self, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply an agent response event and return its broadcast payload."""
        transcript = payload.get("transcript", "")
        response = payload.get("response_text", "")
        if transcript and self.transcripts:
            for entry in reversed(self.transcripts):
                if entry.device_id == device_id and entry.transcript == transcript:
                    entry.response = response
                    break
        return self.timestamped_device_event(
            device_id,
            transcript=transcript,
            response=response,
        )

    def record_audio_delivered(self, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply an audio-delivered event and return its broadcast payload."""
        return self.timestamped_device_event(
            device_id,
            response_id=payload.get("response_id"),
        )

    def apply_polled_device(self, device_id: str, info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """Merge a polled device payload and return any online/offline transition."""
        was_online = self.devices.get(device_id, DeviceState()).online
        is_online = info.get("online", True)
        self.update_device_state(device_id, info)
        if not was_online and is_online:
            return "device_online", info
        if was_online and not is_online:
            return "device_offline", {"device_id": device_id}
        return None

    def mark_missing_devices_offline(self, current_ids: set[str]) -> list[tuple[str, dict[str, Any]]]:
        """Mark previously online devices offline when missing from a poll result."""
        events: list[tuple[str, dict[str, Any]]] = []
        for device_id, device in self.devices.items():
            if device_id and device_id not in current_ids and device.online:
                device.online = False
                events.append(("device_offline", {"device_id": device_id}))
        return events

    def transcript_listing(self) -> dict[str, Any]:
        """Return the serialized transcript view used by the HTTP API."""
        return {
            "transcripts": self.transcript_payloads(self.transcripts[-self.api_transcript_limit:]),
            "count": len(self.transcripts),
        }

    def device_payload(self, device: DeviceState) -> dict[str, Any]:
        """Serialize a device state for HTTP/SSE payloads."""
        return {
            "device_id": device.device_id,
            "device_type": device.device_type,
            "session_id": device.session_id,
            "online": device.online,
            "connected_at": device.connected_at,
            "last_seen": device.last_seen,
            "state": device.state,
            "capabilities": device.capabilities,
            "muted_until": device.muted_until,
            "audio_cache_bytes": device.audio_cache_bytes,
        }

    def transcript_payload(self, entry: TranscriptEntry) -> dict[str, str]:
        """Serialize a transcript entry for HTTP/SSE payloads."""
        return {
            "timestamp": entry.timestamp,
            "device_id": entry.device_id,
            "transcript": entry.transcript,
            "response": entry.response,
            "stream_id": entry.stream_id,
        }

    def transcript_payloads(self, entries: list[TranscriptEntry]) -> list[dict[str, str]]:
        """Serialize a list of transcript entries."""
        return [self.transcript_payload(entry) for entry in entries]

    def timestamped_device_event(self, device_id: str, **payload: Any) -> dict[str, Any]:
        """Build a device event payload with a server timestamp."""
        return {
            "device_id": device_id,
            **payload,
            "timestamp": self._now_factory(),
        }

    def _utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
