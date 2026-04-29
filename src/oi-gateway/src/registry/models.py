"""Data models for the device registry."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class DeviceInfo:
    """Complete device record.

    Stored persistently in SQLite and kept up-to-date as the device
    connects, disconnects, and reports state.
    """

    device_id: str
    device_type: str
    session_id: str
    # Optional fields default to None; callers or _row_to_info fill them in.
    connected_at: datetime | None = None
    last_seen: datetime | None = None
    capabilities: dict[str, Any] = None
    resume_token: str | None = None
    nonce: str | None = None
    state: dict[str, Any] = None
    audio_cache_bytes: int = 0
    muted_until: datetime | None = None
    character_pack_id: str | None = None  # Assigned character pack for this device
    # Stability fields
    last_interaction: datetime | None = None  # Track last user interaction
    reconnect_count: int = 0  # Track reconnection attempts
    foreground_priority: int = 0  # Priority for foreground selection (higher = more priority)
    heartbeat_timeout: float = 30.0  # Seconds before device marked unhealthy
    last_heartbeat: datetime | None = None  # Last heartbeat received
    is_healthy: bool = True  # Device health status

    def __post_init__(self) -> None:
        """Normalise None defaults for mutable fields."""
        if self.capabilities is None:
            self.capabilities = {}
        if self.state is None:
            self.state = {}
