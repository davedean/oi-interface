"""Character packs for visual status display on devices.

This module provides the character pack system for rendering semantic states
on tiny devices like M5StickS3.

Required semantic states:
- idle: waiting for input
- listening: recording audio
- uploading: sending audio to server
- thinking: agent deciding
- response_cached: response ready on device
- playing: audio playing
- confirm: awaiting user choice
- muted: suppressed until timestamp
- offline: no gateway connection
- error: fault in system
- safe_mode: watchdog recovery
- task_running: long-running task in progress
- blocked: blocked on human input

Optional overlays:
- battery_low
- wifi_weak
- tool_running
- code_task
- home_task
- calendar_task
- wiki_update
- private_content
- remote_connection
- cloud_model
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


# ------------------------------------------------------------------
# Semantic States and Overlays
# ------------------------------------------------------------------

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


# ------------------------------------------------------------------
# Data Models
# ------------------------------------------------------------------

@dataclass
class StateConfig:
    """Configuration for a semantic state."""
    sprite: str
    label: str
    animation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "sprite": self.sprite,
            "label": self.label,
            "animation": self.animation,
        }


@dataclass
class CharacterPack:
    """Character pack definition.

    Attributes:
        pack_id: Unique identifier for the pack
        target: Target device type (e.g., "tiny_135x240")
        format: Asset format (indexed_png, rgb565, spritesheet)
        states: Mapping of semantic state to state configuration
        version: Pack version string
        overlays: Optional mapping of overlay state to configuration
    """
    pack_id: str
    target: str
    format: str
    states: dict[str, StateConfig]
    version: str = "1.0"
    overlays: dict[str, StateConfig] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation for API responses."""
        return {
            "pack_id": self.pack_id,
            "target": self.target,
            "format": self.format,
            "version": self.version,
            "states": {
                name: cfg.to_dict()
                for name, cfg in self.states.items()
            },
            "overlays": {
                name: cfg.to_dict()
                for name, cfg in (self.overlays or {}).items()
            } if self.overlays else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CharacterPack:
        """Create from dictionary representation."""
        states = {
            name: StateConfig(**cfg)
            for name, cfg in data.get("states", {}).items()
        }
        overlays = None
        if data.get("overlays"):
            overlays = {
                name: StateConfig(**cfg)
                for name, cfg in data["overlays"].items()
            }
        return cls(
            pack_id=data["pack_id"],
            target=data["target"],
            format=data["format"],
            states=states,
            version=data.get("version", "1.0"),
            overlays=overlays,
        )


# ------------------------------------------------------------------
# Store
# ------------------------------------------------------------------

# SQLite schema for character packs
_CHARACTER_PACKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS character_packs (
    pack_id    TEXT PRIMARY KEY,
    target     TEXT NOT NULL,
    format     TEXT NOT NULL,
    states_json TEXT NOT NULL,
    overlays_json TEXT,
    version    TEXT DEFAULT '1.0'
);
"""


class CharacterPackStore:
    """SQLite-backed store for character packs.

    Parameters
    ----------
    db_path : str
        Path to the SQLite database file.
    """

    def __init__(self, db_path: str = "character_packs.db") -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_CHARACTER_PACKS_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def upsert_pack(self, pack: CharacterPack) -> None:
        """Insert or replace a character pack."""
        self._conn.execute(
            """
            INSERT OR REPLACE INTO character_packs
                (pack_id, target, format, states_json, overlays_json, version)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                pack.pack_id,
                pack.target,
                pack.format,
                json.dumps({
                    name: cfg.to_dict()
                    for name, cfg in pack.states.items()
                }),
                json.dumps({
                    name: cfg.to_dict()
                    for name, cfg in (pack.overlays or {}).items()
                }) if pack.overlays else None,
                pack.version,
            ),
        )
        self._conn.commit()

    def get_pack(self, pack_id: str) -> CharacterPack | None:
        """Retrieve a character pack by pack_id, or None if not found."""
        row = self._conn.execute(
            "SELECT * FROM character_packs WHERE pack_id = ?",
            (pack_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_pack(row)

    def list_packs(self) -> list[CharacterPack]:
        """Return all registered character packs."""
        rows = self._conn.execute("SELECT * FROM character_packs").fetchall()
        return [self._row_to_pack(row) for row in rows]

    def delete_pack(self, pack_id: str) -> None:
        """Delete a character pack."""
        self._conn.execute(
            "DELETE FROM character_packs WHERE pack_id = ?",
            (pack_id,),
        )
        self._conn.commit()

    def get_packs_by_target(self, target: str) -> list[CharacterPack]:
        """Return all packs for a specific target device type."""
        rows = self._conn.execute(
            "SELECT * FROM character_packs WHERE target = ?",
            (target,),
        ).fetchall()
        return [self._row_to_pack(row) for row in rows]

    def _row_to_pack(self, row: sqlite3.Row) -> CharacterPack:
        """Convert a DB row to a CharacterPack instance."""
        states_data = json.loads(row["states_json"])
        states = {
            name: StateConfig(**cfg)
            for name, cfg in states_data.items()
        }
        overlays = None
        if row["overlays_json"]:
            overlays_data = json.loads(row["overlays_json"])
            overlays = {
                name: StateConfig(**cfg)
                for name, cfg in overlays_data.items()
            }
        return CharacterPack(
            pack_id=row["pack_id"],
            target=row["target"],
            format=row["format"],
            states=states,
            version=row["version"] or "1.0",
            overlays=overlays,
        )


# ------------------------------------------------------------------
# Service
# ------------------------------------------------------------------

class CharacterPackService:
    """Service for managing character packs.

    Parameters
    ----------
    store : CharacterPackStore
        Persistence layer for character packs.
    """

    def __init__(self, store: CharacterPackStore) -> None:
        self._store = store

    def register_pack(self, pack: CharacterPack) -> bool:
        """Register a character pack.

        Returns True if registered, False if pack_id already exists.
        """
        if self._store.get_pack(pack.pack_id) is not None:
            return False  # Already exists
        self._store.upsert_pack(pack)
        return True

    def get_pack(self, pack_id: str) -> CharacterPack | None:
        """Get a character pack by pack_id."""
        return self._store.get_pack(pack_id)

    def list_packs(self) -> list[CharacterPack]:
        """List all registered character packs."""
        return self._store.list_packs()

    def get_packs_by_target(self, target: str) -> list[CharacterPack]:
        """Get all packs for a specific target device type."""
        return self._store.get_packs_by_target(target)

    def validate_pack(self, pack: CharacterPack) -> tuple[bool, list[str]]:
        """Validate a character pack.

        Returns (is_valid, list_of_errors).
        """
        return PackValidator.validate(pack)


# ------------------------------------------------------------------
# Built-in Character Packs
# ------------------------------------------------------------------

class BuiltInPacks:
    """Factory for built-in character packs.

    These packs are created on module load and can be registered
    with a CharacterPackService.
    """

    _packs: list[CharacterPack] = []

    @classmethod
    def list(cls) -> list[CharacterPack]:
        """Return all built-in packs."""
        if not cls._packs:
            cls._packs = [
                cls._create_synth_goblin(),
                cls._create_pixel_robot(),
                cls._create_minimal_blob(),
                cls._create_retro_terminal(),
                cls._create_wise_owl(),
                cls._create_cute_cat(),
                cls._create_geometric_glyph(),
                cls._create_nature_leaf(),
                cls._create_neon_fox(),
                cls._create_crystal_gem(),
            ]
        return cls._packs

    @classmethod
    def _create_synth_goblin(cls) -> CharacterPack:
        """Create the Synth Goblin character pack.

        A friendly, expressive character for M5Stick devices.
        """
        states = {
            "idle": StateConfig(
                sprite="goblin-idle.png",
                label="Ready",
                animation=None,
            ),
            "listening": StateConfig(
                sprite="goblin-listen.png",
                label="Listening",
                animation="pulse",
            ),
            "uploading": StateConfig(
                sprite="goblin-upload.png",
                label="Uploading",
                animation="pulse",
            ),
            "thinking": StateConfig(
                sprite="goblin-think.png",
                label="Thinking",
                animation="spin",
            ),
            "response_cached": StateConfig(
                sprite="goblin-ready.png",
                label="Ready",
                animation=None,
            ),
            "playing": StateConfig(
                sprite="goblin-speak.png",
                label="Speaking",
                animation="waveform",
            ),
            "confirm": StateConfig(
                sprite="goblin-confirm.png",
                label="Confirm?",
                animation="pulse",
            ),
            "muted": StateConfig(
                sprite="goblin-mute.png",
                label="Muted",
                animation=None,
            ),
            "offline": StateConfig(
                sprite="goblin-offline.png",
                label="Offline",
                animation="fade",
            ),
            "error": StateConfig(
                sprite="goblin-error.png",
                label="Error",
                animation="pulse_red",
            ),
            "safe_mode": StateConfig(
                sprite="goblin-safe.png",
                label="Safe Mode",
                animation="blink",
            ),
            "task_running": StateConfig(
                sprite="goblin-task.png",
                label="Working",
                animation="spin",
            ),
            "blocked": StateConfig(
                sprite="goblin-blocked.png",
                label="Waiting",
                animation="fade",
            ),
        }
        overlays = {
            "battery_low": StateConfig(
                sprite="overlay-battery-low.png",
                label="Low Battery",
                animation="blink",
            ),
            "wifi_weak": StateConfig(
                sprite="overlay-wifi-weak.png",
                label="Weak Signal",
                animation=None,
            ),
            "tool_running": StateConfig(
                sprite="overlay-tool.png",
                label="Tool Running",
                animation="spin",
            ),
        }
        return CharacterPack(
            pack_id="synth-goblin",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
            version="1.0",
            overlays=overlays,
        )

    @classmethod
    def _create_pixel_robot(cls) -> CharacterPack:
        """Create a pixel-art robot character pack."""
        states = {
            "idle": StateConfig(sprite="robot-idle.png", label="Online", animation=None),
            "listening": StateConfig(sprite="robot-listen.png", label="Hear", animation="pulse"),
            "uploading": StateConfig(sprite="robot-upload.png", label="Send", animation="spin"),
            "thinking": StateConfig(sprite="robot-think.png", label="Think", animation="spin"),
            "response_cached": StateConfig(sprite="robot-ready.png", label="Ready", animation=None),
            "playing": StateConfig(sprite="robot-speak.png", label="Talk", animation="waveform"),
            "confirm": StateConfig(sprite="robot-confirm.png", label="OK?", animation="pulse"),
            "muted": StateConfig(sprite="robot-mute.png", label="Mute", animation=None),
            "offline": StateConfig(sprite="robot-offline.png", label="Off", animation="fade"),
            "error": StateConfig(sprite="robot-error.png", label="Err", animation="pulse_red"),
            "safe_mode": StateConfig(sprite="robot-safe.png", label="Safe", animation="blink"),
            "task_running": StateConfig(sprite="robot-task.png", label="Work", animation="spin"),
            "blocked": StateConfig(sprite="robot-blocked.png", label="Wait", animation="fade"),
        }
        return CharacterPack(
            pack_id="pixel-robot",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
            version="1.0",
        )

    @classmethod
    def _create_minimal_blob(cls) -> CharacterPack:
        """Create a minimal blob character pack."""
        states = {
            "idle": StateConfig(sprite="blob-idle.png", label="•", animation=None),
            "listening": StateConfig(sprite="blob-listen.png", label="•", animation="pulse"),
            "uploading": StateConfig(sprite="blob-upload.png", label="↑", animation="spin"),
            "thinking": StateConfig(sprite="blob-think.png", label="...", animation="spin"),
            "response_cached": StateConfig(sprite="blob-ready.png", label="✓", animation=None),
            "playing": StateConfig(sprite="blob-speak.png", label="♪", animation="waveform"),
            "confirm": StateConfig(sprite="blob-confirm.png", label="?", animation="pulse"),
            "muted": StateConfig(sprite="blob-mute.png", label="⊘", animation=None),
            "offline": StateConfig(sprite="blob-offline.png", label="○", animation="fade"),
            "error": StateConfig(sprite="blob-error.png", label="!", animation="pulse_red"),
            "safe_mode": StateConfig(sprite="blob-safe.png", label="⚠", animation="blink"),
            "task_running": StateConfig(sprite="blob-task.png", label="▶", animation="spin"),
            "blocked": StateConfig(sprite="blob-blocked.png", label="⏸", animation="fade"),
        }
        return CharacterPack(
            pack_id="minimal-blob",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
            version="1.0",
        )

    @classmethod
    def _create_retro_terminal(cls) -> CharacterPack:
        """Create a retro terminal character pack."""
        states = {
            "idle": StateConfig(sprite="term-idle.png", label="$", animation=None),
            "listening": StateConfig(sprite="term-listen.png", label="$", animation="blink"),
            "uploading": StateConfig(sprite="term-upload.png", label="^", animation="spin"),
            "thinking": StateConfig(sprite="term-think.png", label="...", animation="spin"),
            "response_cached": StateConfig(sprite="term-ready.png", label="$ ✓", animation=None),
            "playing": StateConfig(sprite="term-speak.png", label="$ ▷", animation="waveform"),
            "confirm": StateConfig(sprite="term-confirm.png", label="[?]", animation="pulse"),
            "muted": StateConfig(sprite="term-mute.png", label="$ ⊘", animation=None),
            "offline": StateConfig(sprite="term-offline.png", label="$ ×", animation="fade"),
            "error": StateConfig(sprite="term-error.png", label="$ !", animation="pulse_red"),
            "safe_mode": StateConfig(sprite="term-safe.png", label="!WARN!", animation="blink"),
            "task_running": StateConfig(sprite="term-task.png", label="$ ▶", animation="spin"),
            "blocked": StateConfig(sprite="term-blocked.png", label="$ ⏸", animation="fade"),
        }
        return CharacterPack(
            pack_id="retro-terminal",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
            version="1.0",
        )

    @classmethod
    def _create_wise_owl(cls) -> CharacterPack:
        """Create a wise owl character pack."""
        states = {
            "idle": StateConfig(sprite="owl-idle.png", label=" Awake", animation=None),
            "listening": StateConfig(sprite="owl-listen.png", label="Watching", animation="pulse"),
            "uploading": StateConfig(sprite="owl-upload.png", label="Sending", animation="spin"),
            "thinking": StateConfig(sprite="owl-think.png", label="Pondering", animation="spin"),
            "response_cached": StateConfig(sprite="owl-ready.png", label="Ready", animation=None),
            "playing": StateConfig(sprite="owl-speak.png", label="Speaking", animation="waveform"),
            "confirm": StateConfig(sprite="owl-confirm.png", label="Confirm?", animation="pulse"),
            "muted": StateConfig(sprite="owl-mute.png", label="Silent", animation=None),
            "offline": StateConfig(sprite="owl-offline.png", label="Asleep", animation="fade"),
            "error": StateConfig(sprite="owl-error.png", label="Alert!", animation="pulse_red"),
            "safe_mode": StateConfig(sprite="owl-safe.png", label="Safe Mode", animation="blink"),
            "task_running": StateConfig(sprite="owl-task.png", label="Observing", animation="spin"),
            "blocked": StateConfig(sprite="owl-blocked.png", label="Waiting", animation="fade"),
        }
        overlays = {
            "battery_low": StateConfig(sprite="overlay-battery-low.png", label="Low", animation="blink"),
            "wifi_weak": StateConfig(sprite="overlay-wifi-weak.png", label="Weak Signal", animation=None),
        }
        return CharacterPack(
            pack_id="wise-owl",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
            version="1.0",
            overlays=overlays,
        )

    @classmethod
    def _create_cute_cat(cls) -> CharacterPack:
        """Create a cute cat character pack."""
        states = {
            "idle": StateConfig(sprite="cat-idle.png", label="Relaxing", animation=None),
            "listening": StateConfig(sprite="cat-listen.png", label="Alert!", animation="pulse"),
            "uploading": StateConfig(sprite="cat-upload.png", label="Purring", animation="spin"),
            "thinking": StateConfig(sprite="cat-think.png", label="Puzzling", animation="spin"),
            "response_cached": StateConfig(sprite="cat-ready.png", label="Purr", animation=None),
            "playing": StateConfig(sprite="cat-speak.png", label="Meow!", animation="waveform"),
            "confirm": StateConfig(sprite="cat-confirm.png", label="Yes?", animation="pulse"),
            "muted": StateConfig(sprite="cat-mute.png", label="Shh!", animation=None),
            "offline": StateConfig(sprite="cat-offline.png", label="Napping", animation="fade"),
            "error": StateConfig(sprite="cat-error.png", label="Hiss!", animation="pulse_red"),
            "safe_mode": StateConfig(sprite="cat-safe.png", label="Safe", animation="blink"),
            "task_running": StateConfig(sprite="cat-task.png", label="Hunting", animation="spin"),
            "blocked": StateConfig(sprite="cat-blocked.png", label="Waiting", animation="fade"),
        }
        return CharacterPack(
            pack_id="cute-cat",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
            version="1.0",
        )

    @classmethod
    def _create_geometric_glyph(cls) -> CharacterPack:
        """Create a geometric glyph character pack."""
        states = {
            "idle": StateConfig(sprite="glyph-idle.png", label="◇", animation=None),
            "listening": StateConfig(sprite="glyph-listen.png", label="△", animation="pulse"),
            "uploading": StateConfig(sprite="glyph-upload.png", label="⬆", animation="spin"),
            "thinking": StateConfig(sprite="glyph-think.png", label="◈", animation="spin"),
            "response_cached": StateConfig(sprite="glyph-ready.png", label="✓", animation=None),
            "playing": StateConfig(sprite="glyph-speak.png", label="◇ ▷", animation="waveform"),
            "confirm": StateConfig(sprite="glyph-confirm.png", label="◁?◀", animation="pulse"),
            "muted": StateConfig(sprite="glyph-mute.png", label="⊘", animation=None),
            "offline": StateConfig(sprite="glyph-offline.png", label="○", animation="fade"),
            "error": StateConfig(sprite="glyph-error.png", label="✕", animation="pulse_red"),
            "safe_mode": StateConfig(sprite="glyph-safe.png", label="⚠", animation="blink"),
            "task_running": StateConfig(sprite="glyph-task.png", label="▶", animation="spin"),
            "blocked": StateConfig(sprite="glyph-blocked.png", label="⏸", animation="fade"),
        }
        return CharacterPack(
            pack_id="geometric-glyph",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
            version="1.0",
        )

    @classmethod
    def _create_nature_leaf(cls) -> CharacterPack:
        """Create a nature/leaf character pack."""
        states = {
            "idle": StateConfig(sprite="leaf-idle.png", label="Resting", animation=None),
            "listening": StateConfig(sprite="leaf-listen.png", label="Listening", animation="pulse"),
            "uploading": StateConfig(sprite="leaf-upload.png", label="Growing", animation="spin"),
            "thinking": StateConfig(sprite="leaf-think.png", label="Blooming", animation="spin"),
            "response_cached": StateConfig(sprite="leaf-ready.png", label="Ready", animation=None),
            "playing": StateConfig(sprite="leaf-speak.png", label="Swaying", animation="waveform"),
            "confirm": StateConfig(sprite="leaf-confirm.png", label="Sprout?", animation="pulse"),
            "muted": StateConfig(sprite="leaf-mute.png", label="Still", animation=None),
            "offline": StateConfig(sprite="leaf-offline.png", label="Dormant", animation="fade"),
            "error": StateConfig(sprite="leaf-error.png", label="Wilted", animation="pulse_red"),
            "safe_mode": StateConfig(sprite="leaf-safe.png", label="Protected", animation="blink"),
            "task_running": StateConfig(sprite="leaf-task.png", label="Growing", animation="spin"),
            "blocked": StateConfig(sprite="leaf-blocked.png", label="Waiting", animation="fade"),
        }
        overlays = {
            "battery_low": StateConfig(sprite="overlay-battery-low.png", label="Needs Water", animation="blink"),
            "wifi_weak": StateConfig(sprite="overlay-wifi-weak.png", label="Weak Signal", animation=None),
        }
        return CharacterPack(
            pack_id="nature-leaf",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
            version="1.0",
            overlays=overlays,
        )

    @classmethod
    def _create_neon_fox(cls) -> CharacterPack:
        """Create a neon cyberpunk fox character pack."""
        states = {
            "idle": StateConfig(sprite="fox-idle.png", label="Ready", animation=None),
            "listening": StateConfig(sprite="fox-listen.png", label="Scanning", animation="pulse"),
            "uploading": StateConfig(sprite="fox-upload.png", label="Uploading", animation="spin"),
            "thinking": StateConfig(sprite="fox-think.png", label="Hacking", animation="spin"),
            "response_cached": StateConfig(sprite="fox-ready.png", label="Done", animation=None),
            "playing": StateConfig(sprite="fox-speak.png", label="Transmit", animation="waveform"),
            "confirm": StateConfig(sprite="fox-confirm.png", label="Confirm?", animation="pulse"),
            "muted": StateConfig(sprite="fox-mute.png", label="Silent", animation=None),
            "offline": StateConfig(sprite="fox-offline.png", label="Disconnected", animation="fade"),
            "error": StateConfig(sprite="fox-error.png", label="ERROR", animation="pulse_red"),
            "safe_mode": StateConfig(sprite="fox-safe.png", label="Safe Mode", animation="blink"),
            "task_running": StateConfig(sprite="fox-task.png", label="Running", animation="spin"),
            "blocked": StateConfig(sprite="fox-blocked.png", label="Blocked", animation="fade"),
        }
        overlays = {
            "tool_running": StateConfig(sprite="overlay-tool.png", label="Executing", animation="spin"),
            "code_task": StateConfig(sprite="overlay-code.png", label="Coding", animation="spin"),
            "private_content": StateConfig(sprite="overlay-private.png", label="Encrypted", animation=None),
            "remote_connection": StateConfig(sprite="overlay-remote.png", label="Remote", animation="pulse"),
        }
        return CharacterPack(
            pack_id="neon-fox",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
            version="1.0",
            overlays=overlays,
        )

    @classmethod
    def _create_crystal_gem(cls) -> CharacterPack:
        """Create a crystal gem character pack."""
        states = {
            "idle": StateConfig(sprite="gem-idle.png", label="Radiant", animation=None),
            "listening": StateConfig(sprite="gem-listen.png", label="Gleaming", animation="pulse"),
            "uploading": StateConfig(sprite="gem-upload.png", label="Charging", animation="spin"),
            "thinking": StateConfig(sprite="gem-think.png", label="Refracting", animation="spin"),
            "response_cached": StateConfig(sprite="gem-ready.png", label="Shine", animation=None),
            "playing": StateConfig(sprite="gem-speak.png", label="Glow", animation="waveform"),
            "confirm": StateConfig(sprite="gem-confirm.png", label="Clear?", animation="pulse"),
            "muted": StateConfig(sprite="gem-mute.png", label="Dull", animation=None),
            "offline": StateConfig(sprite="gem-offline.png", label="Dim", animation="fade"),
            "error": StateConfig(sprite="gem-error.png", label="Crack!", animation="pulse_red"),
            "safe_mode": StateConfig(sprite="gem-safe.png", label="Stable", animation="blink"),
            "task_running": StateConfig(sprite="gem-task.png", label="Polishing", animation="spin"),
            "blocked": StateConfig(sprite="gem-blocked.png", label="Suspended", animation="fade"),
        }
        overlays = {
            "battery_low": StateConfig(sprite="overlay-battery-low.png", label="Low Energy", animation="blink"),
            "wifi_weak": StateConfig(sprite="overlay-wifi-weak.png", label="Weak Signal", animation=None),
            "cloud_model": StateConfig(sprite="overlay-cloud.png", label="Cloud", animation="pulse"),
        }
        return CharacterPack(
            pack_id="crystal-gem",
            target="tiny_135x240",
            format="indexed_png",
            states=states,
            version="1.0",
            overlays=overlays,
        )


# ------------------------------------------------------------------
# Device Renderer
# ------------------------------------------------------------------

@dataclass
class RenderInstruction:
    """A rendering instruction for a device."""
    sprite_path: str
    label: str
    animation: str | None
    overlay_sprite_path: str | None = None
    overlay_label: str | None = None


class DeviceRenderer:
    """Renders character packs to device-specific formats.

    This renderer converts semantic state + overlay into DATP commands
    that devices can understand.
    """

    # Maximum label length for different device types
    MAX_LABEL_LENGTHS = {
        "tiny_135x240": 12,
        "watch_240x280": 16,
        "phone_390x450": 32,
    }

    def __init__(self, pack: CharacterPack):
        """Initialize renderer with a character pack."""
        self.pack = pack

    def render(self, state: str, overlay: str | None = None, custom_label: str | None = None) -> RenderInstruction:
        """Render a semantic state to device instructions.

        Parameters
        ----------
        state : str
            The semantic state name (e.g., "thinking", "idle")
        overlay : str | None
            Optional overlay to apply (e.g., "battery_low", "tool_running")
        custom_label : str | None
            Optional custom label to override the pack's default

        Returns
        -------
        RenderInstruction
            Rendering instructions for the device

        Raises
        ------
        ValueError
            If state or overlay is not found in the pack
        """
        # Get the state configuration
        if state not in self.pack.states:
            raise ValueError(f"State '{state}' not found in pack '{self.pack.pack_id}'")

        state_cfg = self.pack.states[state]

        # Determine the label (custom overrides pack default)
        label = custom_label if custom_label else state_cfg.label

        # Validate label length
        max_len = self.MAX_LABEL_LENGTHS.get(self.pack.target, 16)
        if len(label) > max_len:
            label = label[: max_len - 1] + "…"

        # Get overlay if specified
        overlay_sprite_path = None
        overlay_label = None
        if overlay and self.pack.overlays:
            if overlay not in self.pack.overlays:
                raise ValueError(f"Overlay '{overlay}' not found in pack '{self.pack.pack_id}'")
            overlay_cfg = self.pack.overlays[overlay]
            overlay_sprite_path = overlay_cfg.sprite
            overlay_label = overlay_cfg.label

        return RenderInstruction(
            sprite_path=state_cfg.sprite,
            label=label,
            animation=state_cfg.animation,
            overlay_sprite_path=overlay_sprite_path,
            overlay_label=overlay_label,
        )

    def to_datp_command(self, state: str, overlay: str | None = None, custom_label: str | None = None) -> dict:
        """Convert render instructions to a DATP display command.

        Returns a DATP command payload that can be sent to a device.
        """
        instruction = self.render(state, overlay, custom_label)

        return {
            "op": "character.set_state",
            "args": {
                "sprite": instruction.sprite_path,
                "label": instruction.label,
                "animation": instruction.animation,
                "overlay": instruction.overlay_sprite_path,
                "overlay_label": instruction.overlay_label,
                "pack_id": self.pack.pack_id,
                "target": self.pack.target,
            },
        }

    def get_available_states(self) -> list[str]:
        """Return list of states available in this pack."""
        return list(self.pack.states.keys())

    def get_available_overlays(self) -> list[str] | None:
        """Return list of overlays available in this pack, or None if none."""
        if self.pack.overlays:
            return list(self.pack.overlays.keys())
        return None


# ------------------------------------------------------------------
# Enhanced Pack Validator
# ------------------------------------------------------------------

class PackValidator:
    """Enhanced validator for character pack integrity.

    Performs comprehensive validation beyond basic required state checks.
    """

    MAX_SPRITE_PATH_LENGTH = 128
    MAX_LABEL_LENGTH = 32
    VALID_ANIMATIONS = {None, "pulse", "spin", "blink", "fade", "waveform", "pulse_red"}
    VALID_TARGETS = ["tiny_135x240", "watch_240x280", "phone_390x450"]
    VALID_FORMATS = ["indexed_png", "rgb565", "spritesheet"]

    @classmethod
    def validate(cls, pack: CharacterPack) -> tuple[bool, list[str]]:
        """Validate a character pack comprehensively.

        Returns (is_valid, list_of_errors).
        """
        errors = []

        # Check required states
        for required in REQUIRED_STATES:
            if required not in pack.states:
                errors.append(f"Missing required state: {required}")

        # Validate target
        if pack.target not in cls.VALID_TARGETS:
            errors.append(f"Invalid target '{pack.target}'. Valid: {cls.VALID_TARGETS}")

        # Validate format
        if pack.format not in cls.VALID_FORMATS:
            errors.append(f"Invalid format '{pack.format}'. Valid: {cls.VALID_FORMATS}")

        # Validate each state configuration
        for state_name, state_cfg in pack.states.items():
            # Validate sprite path
            if not state_cfg.sprite:
                errors.append(f"State '{state_name}': sprite path is required")
            elif len(state_cfg.sprite) > cls.MAX_SPRITE_PATH_LENGTH:
                errors.append(f"State '{state_name}': sprite path too long ({len(state_cfg.sprite)} > {cls.MAX_SPRITE_PATH_LENGTH})")

            # Validate label
            if not state_cfg.label:
                errors.append(f"State '{state_name}': label is required")
            elif len(state_cfg.label) > cls.MAX_LABEL_LENGTH:
                errors.append(f"State '{state_name}': label too long ({len(state_cfg.label)} > {cls.MAX_LABEL_LENGTH})")

            # Validate animation
            if state_cfg.animation not in cls.VALID_ANIMATIONS:
                errors.append(f"State '{state_name}': invalid animation '{state_cfg.animation}'. Valid: {cls.VALID_ANIMATIONS}")

        # Validate overlays if present
        if pack.overlays:
            for overlay_name, overlay_cfg in pack.overlays.items():
                if not overlay_cfg.sprite:
                    errors.append(f"Overlay '{overlay_name}': sprite path is required")
                if not overlay_cfg.label:
                    errors.append(f"Overlay '{overlay_name}': label is required")
                if overlay_cfg.animation not in cls.VALID_ANIMATIONS:
                    errors.append(f"Overlay '{overlay_name}': invalid animation '{overlay_cfg.animation}'")

        # Check pack_id format
        if not pack.pack_id or not pack.pack_id.replace("-", "").replace("_", "").isalnum():
            errors.append(f"Invalid pack_id format: '{pack.pack_id}' (use alphanumeric, hyphens, underscores)")

        # Check version format (basic semver-like check)
        if pack.version:
            parts = pack.version.split(".")
            if len(parts) < 2 or not all(p.isdigit() for p in parts[:2]):
                errors.append(f"Invalid version format: '{pack.version}' (use semver like '1.0' or '1.2.3')")

        return len(errors) == 0, errors


# ------------------------------------------------------------------
# Experimental Pack Generator
# ------------------------------------------------------------------

class PackGenerator:
    """Experimental pack generator for creating packs from templates.

    This is an experimental feature that generates character packs
    based on style templates and parameters. It does not use AI - it
    applies predefined templates with configurable parameters.
    """

    # Style templates define the naming patterns and themes
    STYLE_TEMPLATES = {
        "animal": {
            "idle": "{name}-idle.png",
            "listening": "{name}-listen.png",
            "uploading": "{name}-upload.png",
            "thinking": "{name}-think.png",
            "response_cached": "{name}-ready.png",
            "playing": "{name}-speak.png",
            "confirm": "{name}-confirm.png",
            "muted": "{name}-mute.png",
            "offline": "{name}-offline.png",
            "error": "{name}-error.png",
            "safe_mode": "{name}-safe.png",
            "task_running": "{name}-task.png",
            "blocked": "{name}-blocked.png",
        },
        "robot": {
            "idle": "robot-idle.png",
            "listening": "robot-listen.png",
            "uploading": "robot-upload.png",
            "thinking": "robot-think.png",
            "response_cached": "robot-ready.png",
            "playing": "robot-speak.png",
            "confirm": "robot-confirm.png",
            "muted": "robot-mute.png",
            "offline": "robot-offline.png",
            "error": "robot-error.png",
            "safe_mode": "robot-safe.png",
            "task_running": "robot-task.png",
            "blocked": "robot-blocked.png",
        },
        "minimal": {
            "idle": "min-idle.png",
            "listening": "min-listen.png",
            "uploading": "min-upload.png",
            "thinking": "min-think.png",
            "response_cached": "min-ready.png",
            "playing": "min-speak.png",
            "confirm": "min-confirm.png",
            "muted": "min-mute.png",
            "offline": "min-offline.png",
            "error": "min-error.png",
            "safe_mode": "min-safe.png",
            "task_running": "min-task.png",
            "blocked": "min-blocked.png",
        },
    }

    # Label templates for different styles
    LABEL_TEMPLATES = {
        "friendly": {
            "idle": "Hello!",
            "listening": "I hear you",
            "uploading": "Sending",
            "thinking": "Let me think",
            "response_cached": "Got it!",
            "playing": "Talking",
            "confirm": "OK?",
            "muted": "Quiet time",
            "offline": "Away",
            "error": "Oops!",
            "safe_mode": "Resting",
            "task_running": "Working",
            "blocked": "Hold on",
        },
        "technical": {
            "idle": "Online",
            "listening": "Receiving",
            "uploading": "Transmit",
            "thinking": "Process",
            "response_cached": "Ready",
            "playing": "Output",
            "confirm": "Confirm",
            "muted": "Muted",
            "offline": "Offline",
            "error": "Error",
            "safe_mode": "Safe",
            "task_running": "Active",
            "blocked": "Wait",
        },
        "minimal": {
            "idle": "•",
            "listening": "○",
            "uploading": "↑",
            "thinking": "...",
            "response_cached": "✓",
            "playing": "♪",
            "confirm": "?",
            "muted": "⊘",
            "offline": "○",
            "error": "!",
            "safe_mode": "⚠",
            "task_running": "▶",
            "blocked": "⏸",
        },
    }

    # Animation templates
    ANIMATION_TEMPLATES = {
        "standard": {
            "idle": None,
            "listening": "pulse",
            "uploading": "spin",
            "thinking": "spin",
            "response_cached": None,
            "playing": "waveform",
            "confirm": "pulse",
            "muted": None,
            "offline": "fade",
            "error": "pulse_red",
            "safe_mode": "blink",
            "task_running": "spin",
            "blocked": "fade",
        },
        "calm": {
            "idle": None,
            "listening": "fade",
            "uploading": "fade",
            "thinking": "pulse",
            "response_cached": None,
            "playing": "pulse",
            "confirm": "fade",
            "muted": None,
            "offline": "fade",
            "error": "fade",
            "safe_mode": "fade",
            "task_running": "pulse",
            "blocked": "fade",
        },
    }

    @classmethod
    def generate(
        cls,
        pack_id: str,
        target: str = "tiny_135x240",
        style: str = "robot",
        label_template: str = "technical",
        animation_template: str = "standard",
        custom_labels: dict[str, str] | None = None,
    ) -> CharacterPack:
        """Generate a character pack from templates.

        Parameters
        ----------
        pack_id : str
            Unique identifier for the generated pack
        target : str
            Target device type (default: "tiny_135x240")
        style : str
            Style template to use ("animal", "robot", "minimal")
        label_template : str
            Label template to use ("friendly", "technical", "minimal")
        animation_template : str
            Animation template to use ("standard", "calm")
        custom_labels : dict[str, str] | None
            Optional custom labels to override defaults

        Returns
        -------
        CharacterPack
            A generated character pack

        Raises
        ------
        ValueError
            If template names are invalid
        """
        # Validate templates
        if style not in cls.STYLE_TEMPLATES:
            raise ValueError(f"Unknown style: {style}. Valid: {list(cls.STYLE_TEMPLATES.keys())}")
        if label_template not in cls.LABEL_TEMPLATES:
            raise ValueError(f"Unknown label template: {label_template}. Valid: {list(cls.LABEL_TEMPLATES.keys())}")
        if animation_template not in cls.ANIMATION_TEMPLATES:
            raise ValueError(f"Unknown animation template: {animation_template}. Valid: {list(cls.ANIMATION_TEMPLATES.keys())}")

        style_template = cls.STYLE_TEMPLATES[style]
        labels = cls.LABEL_TEMPLATES[label_template].copy()
        animations = cls.ANIMATION_TEMPLATES[animation_template]

        # Apply custom labels
        if custom_labels:
            labels.update(custom_labels)

        # Build states
        states = {}
        for state_name in REQUIRED_STATES:
            sprite = style_template.get(state_name, f"{state_name}.png")
            label = labels.get(state_name, state_name.replace("_", " ").title())
            animation = animations.get(state_name)

            states[state_name] = StateConfig(
                sprite=sprite,
                label=label,
                animation=animation,
            )

        return CharacterPack(
            pack_id=pack_id,
            target=target,
            format="indexed_png",
            states=states,
            version="1.0",
        )

    @classmethod
    def generate_from_prompt(cls, prompt: str, target: str = "tiny_135x240") -> CharacterPack:
        """Generate a pack from a text prompt (experimental).

        This uses simple keyword matching to select templates.
        It's not AI-powered - just pattern matching.

        Parameters
        ----------
        prompt : str
            A text description (e.g., "friendly robot dog")
        target : str
            Target device type

        Returns
        -------
        CharacterPack
            A generated character pack
        """
        prompt_lower = prompt.lower()

        # Detect style keywords
        if any(w in prompt_lower for w in ["animal", "cat", "dog", "fox", "owl", "bird", "creature"]):
            style = "animal"
        elif any(w in prompt_lower for w in ["minimal", "simple", "basic", "tiny", "symbol"]):
            style = "minimal"
        else:
            style = "robot"

        # Detect label template
        if any(w in prompt_lower for w in ["friendly", "cute", "warm", "soft", "nice"]):
            label_template = "friendly"
        elif any(w in prompt_lower for w in ["minimal", "symbol", "icon", "emoji"]):
            label_template = "minimal"
        else:
            label_template = "technical"

        # Detect animation template
        if any(w in prompt_lower for w in ["calm", "slow", "relaxed", "gentle", "soft"]):
            animation_template = "calm"
        else:
            animation_template = "standard"

        # Generate pack ID from prompt
        # Extract key words and create an ID
        words = [w for w in prompt_lower.replace("-", " ").replace("_", " ").split() if len(w) > 2][:3]
        pack_id = "gen-" + "-".join(words) if words else "gen-custom"

        return cls.generate(
            pack_id=pack_id,
            target=target,
            style=style,
            label_template=label_template,
            animation_template=animation_template,
        )


# ------------------------------------------------------------------
# Exports
# ------------------------------------------------------------------

__all__ = [
    "CharacterPack",
    "StateConfig",
    "SemanticState",
    "Overlay",
    "CharacterPackStore",
    "CharacterPackService",
    "BuiltInPacks",
    "REQUIRED_STATES",
    # Device renderer
    "DeviceRenderer",
    "RenderInstruction",
    # Enhanced validator
    "PackValidator",
    # Experimental generator
    "PackGenerator",
]
