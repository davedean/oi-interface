"""Semantic states, overlays, and constants for character packs."""
from __future__ import annotations

from enum import Enum


class SemanticState(str, Enum):
    """Semantic states for devices."""
    IDLE = "idle"
    LISTENING = "listening"
    UPLOADING = "uploading"
    THINKING = "thinking"
    RESPONSE_CACHED = "response_cached"
    PLAYING = "playing"
    CONFIRM = "confirm"
    MUTED = "muted"
    OFFLINE = "offline"
    ERROR = "error"
    SAFE_MODE = "safe_mode"
    TASK_RUNNING = "task_running"
    BLOCKED = "blocked"


class Overlay(str, Enum):
    """Optional overlays for character display."""
    BATTERY_LOW = "battery_low"
    WIFI_WEAK = "wifi_weak"
    TOOL_RUNNING = "tool_running"
    CODE_TASK = "code_task"
    HOME_TASK = "home_task"
    CALENDAR_TASK = "calendar_task"
    WIKI_UPDATE = "wiki_update"
    PRIVATE_CONTENT = "private_content"
    REMOTE_CONNECTION = "remote_connection"
    CLOUD_MODEL = "cloud_model"


# List of all required state names (for validation)
REQUIRED_STATES = [
    "idle",
    "listening",
    "uploading",
    "thinking",
    "response_cached",
    "playing",
    "confirm",
    "muted",
    "offline",
    "error",
    "safe_mode",
    "task_running",
    "blocked",
]