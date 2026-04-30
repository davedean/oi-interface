"""SQLite persistence layer for the device registry."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from registry.models import DeviceInfo
from utils import dt_to_str, str_to_dt
from runtime_paths import gateway_db_path


# ------------------------------------------------------------------
# Schema
# ------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id        TEXT PRIMARY KEY,
    device_type      TEXT NOT NULL,
    session_id       TEXT,
    connected_at     TEXT,
    last_seen        TEXT,
    capabilities_json TEXT,
    resume_token     TEXT,
    nonce            TEXT,
    state_json       TEXT DEFAULT '{}',
    audio_cache_bytes INTEGER DEFAULT 0,
    muted_until      TEXT,
    character_pack_id TEXT,
    last_interaction TEXT,
    reconnect_count  INTEGER DEFAULT 0,
    foreground_priority INTEGER DEFAULT 0,
    heartbeat_timeout REAL DEFAULT 30.0,
    last_heartbeat   TEXT,
    is_healthy       INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
INSERT OR IGNORE INTO schema_version (version) VALUES (3);
"""

# SQL for upsert used by both sync and async paths.
_UPSERT_SQL = """
    INSERT INTO devices
        (device_id, device_type, session_id, connected_at,
         last_seen, capabilities_json, resume_token, nonce,
         state_json, audio_cache_bytes, muted_until, character_pack_id,
         last_interaction, reconnect_count, foreground_priority,
         heartbeat_timeout, last_heartbeat, is_healthy)
    VALUES
        (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(device_id) DO UPDATE SET
        device_type       = excluded.device_type,
        session_id        = excluded.session_id,
        connected_at      = excluded.connected_at,
        last_seen         = excluded.last_seen,
        capabilities_json = excluded.capabilities_json,
        resume_token      = excluded.resume_token,
        nonce             = excluded.nonce,
        state_json        = excluded.state_json,
        audio_cache_bytes = excluded.audio_cache_bytes,
        muted_until       = excluded.muted_until,
        character_pack_id = excluded.character_pack_id,
        last_interaction  = excluded.last_interaction,
        reconnect_count   = excluded.reconnect_count,
        foreground_priority = excluded.foreground_priority,
        heartbeat_timeout = excluded.heartbeat_timeout,
        last_heartbeat    = excluded.last_heartbeat,
        is_healthy        = excluded.is_healthy;
"""


def _info_to_row(info: DeviceInfo) -> tuple:
    """Build the parameter tuple for _UPSERT_SQL from a DeviceInfo."""
    return (
        info.device_id,
        info.device_type,
        info.session_id,
        dt_to_str(info.connected_at),
        dt_to_str(info.last_seen),
        json.dumps(info.capabilities),
        info.resume_token,
        info.nonce,
        json.dumps(info.state),
        info.audio_cache_bytes,
        dt_to_str(info.muted_until),
        info.character_pack_id,
        dt_to_str(info.last_interaction),
        info.reconnect_count,
        info.foreground_priority,
        info.heartbeat_timeout,
        dt_to_str(info.last_heartbeat),
        int(info.is_healthy),
    )


class DeviceStore:
    """SQLite-backed device record store.

    Provides both synchronous methods (for tests / synchronous callers) and
    async wrappers (for use inside an asyncio event loop without blocking it).
    The async wrappers run the blocking SQLite calls in a :class:`ThreadPoolExecutor`.

    Parameters
    ----------
    db_path : str
        Path to the SQLite database file.

    Supports the context manager protocol for automatic cleanup::

        with DeviceStore("devices.db") as store:
            store.upsert_device(info)
        # executor is shut down and connection is closed here
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        db_path_obj = Path(db_path).expanduser() if db_path is not None else gateway_db_path()
        db_path_obj.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(db_path_obj)
        # Allow sharing the connection across thread-pool threads.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row  # enable named column access
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.execute("PRAGMA journal_mode=WAL;")  # concurrent reads + writes
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._migrate_schema()  # Add missing columns for backward compatibility
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="oi-db-")
        self._closed = False

    def _run(self, fn, *args, **kwargs):
        """Run a blocking function in the thread pool to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(self._executor, lambda: fn(*args, **kwargs))

    def close(self) -> None:
        """Shut down the executor and close the database connection."""
        if self._closed:
            return
        self._executor.shutdown(wait=True)
        self._conn.close()
        self._closed = True

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self) -> "DeviceStore":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Sync API — used by tests and synchronous callers
    # ------------------------------------------------------------------

    def upsert_device(self, info: DeviceInfo) -> None:
        """Insert or replace a device record."""
        self._conn.execute(_UPSERT_SQL, _info_to_row(info))
        self._conn.commit()

    def get_device(self, device_id: str) -> DeviceInfo | None:
        """Retrieve a device record by device_id, or None if not found."""
        row = self._conn.execute(
            "SELECT * FROM devices WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_info(row)

    def get_all_devices(self) -> list[DeviceInfo]:
        """Return all stored device records."""
        rows = self._conn.execute("SELECT * FROM devices").fetchall()
        return [self._row_to_info(row) for row in rows]

    def update_state(self, device_id: str, state: dict[str, Any]) -> None:
        """Update the stored state dict for a device."""
        self._conn.execute(
            "UPDATE devices SET state_json = ? WHERE device_id = ?",
            (json.dumps(state), device_id),
        )
        self._conn.commit()

    def set_character_pack(self, device_id: str, character_pack_id: str | None) -> bool:
        """Set or clear the character pack for a device.

        Returns True if the device was found and updated, False otherwise.
        """
        cursor = self._conn.execute(
            "UPDATE devices SET character_pack_id = ? WHERE device_id = ?",
            (character_pack_id, device_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def remove_device(self, device_id: str) -> None:
        """Delete a device record."""
        self._conn.execute(
            "DELETE FROM devices WHERE device_id = ?",
            (device_id,),
        )
        self._conn.commit()

    def device_seen(self, device_id: str) -> None:
        """Update the last_seen timestamp for a device."""
        self._conn.execute(
            "UPDATE devices SET last_seen = ? WHERE device_id = ?",
            (dt_to_str(datetime.now(timezone.utc)), device_id),
        )
        self._conn.commit()

    def update_last_interaction(self, device_id: str) -> None:
        """Update the last_interaction timestamp for a device."""
        self._conn.execute(
            "UPDATE devices SET last_interaction = ? WHERE device_id = ?",
            (dt_to_str(datetime.now(timezone.utc)), device_id),
        )
        self._conn.commit()

    def update_health(self, device_id: str, is_healthy: bool) -> None:
        """Update the health status for a device."""
        self._conn.execute(
            "UPDATE devices SET is_healthy = ? WHERE device_id = ?",
            (1 if is_healthy else 0, device_id),
        )
        self._conn.commit()

    def update_heartbeat(self, device_id: str) -> None:
        """Update the last_heartbeat timestamp for a device."""
        self._conn.execute(
            "UPDATE devices SET last_heartbeat = ?, is_healthy = 1 WHERE device_id = ?",
            (dt_to_str(datetime.now(timezone.utc)), device_id),
        )
        self._conn.commit()

    def update_reconnect_count(self, device_id: str, count: int) -> None:
        """Update the reconnect count for a device."""
        self._conn.execute(
            "UPDATE devices SET reconnect_count = ? WHERE device_id = ?",
            (count, device_id),
        )
        self._conn.commit()

    def update_foreground_priority(self, device_id: str, priority: int) -> None:
        """Update the foreground priority for a device."""
        self._conn.execute(
            "UPDATE devices SET foreground_priority = ? WHERE device_id = ?",
            (priority, device_id),
        )
        self._conn.commit()

    def set_foreground_priority_highest(self, device_id: str) -> None:
        """Set the device's foreground priority higher than all other devices."""
        # First get max priority from all devices
        row = self._conn.execute("SELECT MAX(foreground_priority) as max_p FROM devices").fetchone()
        max_priority = row["max_p"] if row and row["max_p"] is not None else 0

        # Set this device higher than max
        self._conn.execute(
            "UPDATE devices SET foreground_priority = ? WHERE device_id = ?",
            (max_priority + 1, device_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Async API — offloads blocking calls to a thread pool
    # ------------------------------------------------------------------

    async def upsert_device_async(self, info: DeviceInfo) -> None:
        """Insert or replace a device record (runs in thread pool)."""
        await self._run(self._sync_upsert, info)

    async def get_device_async(self, device_id: str) -> DeviceInfo | None:
        """Retrieve a device record by device_id (runs in thread pool)."""
        return await self._run(self._sync_get, device_id)

    async def get_all_devices_async(self) -> list[DeviceInfo]:
        """Return all stored device records (runs in thread pool)."""
        return await self._run(self._sync_get_all)

    async def update_state_async(self, device_id: str, state: dict[str, Any]) -> None:
        """Update the stored state dict for a device (runs in thread pool)."""
        await self._run(self._sync_update_state, device_id, state)

    async def set_character_pack_async(self, device_id: str, character_pack_id: str | None) -> bool:
        """Set or clear the character pack for a device (runs in thread pool).

        Returns True if the device was found and updated, False otherwise.
        """
        return await self._run(self._sync_set_character_pack, device_id, character_pack_id)

    async def remove_device_async(self, device_id: str) -> None:
        """Delete a device record (runs in thread pool)."""
        await self._run(self._sync_remove, device_id)

    async def device_seen_async(self, device_id: str) -> None:
        """Update the last_seen timestamp for a device (runs in thread pool)."""
        await self._run(self._sync_device_seen, device_id)

    # ------------------------------------------------------------------
    # Sync helpers (called in thread pool by async wrappers)
    # ------------------------------------------------------------------

    def _sync_upsert(self, info: DeviceInfo) -> None:
        self._conn.execute(_UPSERT_SQL, _info_to_row(info))
        self._conn.commit()

    def _sync_get(self, device_id: str) -> DeviceInfo | None:
        row = self._conn.execute(
            "SELECT * FROM devices WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_info(row)

    def _sync_get_all(self) -> list[DeviceInfo]:
        rows = self._conn.execute("SELECT * FROM devices").fetchall()
        return [self._row_to_info(row) for row in rows]

    def _sync_update_state(self, device_id: str, state: dict[str, Any]) -> None:
        self._conn.execute(
            "UPDATE devices SET state_json = ? WHERE device_id = ?",
            (json.dumps(state), device_id),
        )
        self._conn.commit()

    def _sync_set_character_pack(self, device_id: str, character_pack_id: str | None) -> bool:
        cursor = self._conn.execute(
            "UPDATE devices SET character_pack_id = ? WHERE device_id = ?",
            (character_pack_id, device_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def _sync_remove(self, device_id: str) -> None:
        self._conn.execute(
            "DELETE FROM devices WHERE device_id = ?",
            (device_id,),
        )
        self._conn.commit()

    def _sync_device_seen(self, device_id: str) -> None:
        self._conn.execute(
            "UPDATE devices SET last_seen = ? WHERE device_id = ?",
            (dt_to_str(datetime.now(timezone.utc)), device_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Stability features
    # ------------------------------------------------------------------

    async def update_last_interaction_async(self, device_id: str) -> None:
        """Update the last interaction timestamp (runs in thread pool)."""
        await self._run(self._sync_update_last_interaction, device_id)

    def _sync_update_last_interaction(self, device_id: str) -> None:
        """Update the last interaction timestamp for a device."""
        self._conn.execute(
            "UPDATE devices SET last_interaction = ? WHERE device_id = ?",
            (dt_to_str(datetime.now(timezone.utc)), device_id),
        )
        self._conn.commit()

    async def set_foreground_priority_highest_async(self, device_id: str) -> None:
        """Set foreground priority higher than all other devices (runs in thread pool)."""
        await self._run(self._sync_set_foreground_priority_highest, device_id)

    def _sync_set_foreground_priority_highest(self, device_id: str) -> None:
        """Set foreground priority higher than all other devices."""
        row = self._conn.execute("SELECT MAX(foreground_priority) as max_p FROM devices").fetchone()
        max_priority = row["max_p"] if row and row["max_p"] is not None else 0
        self._conn.execute(
            "UPDATE devices SET foreground_priority = ? WHERE device_id = ?",
            (max_priority + 1, device_id),
        )
        self._conn.commit()

    async def update_heartbeat_async(self, device_id: str) -> None:
        """Update the last heartbeat timestamp (runs in thread pool)."""
        await self._run(self._sync_update_heartbeat, device_id)

    def _sync_update_heartbeat(self, device_id: str) -> None:
        """Update the last heartbeat timestamp for a device."""
        self._conn.execute(
            "UPDATE devices SET last_heartbeat = ?, is_healthy = 1 WHERE device_id = ?",
            (dt_to_str(datetime.now(timezone.utc)), device_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Schema Migration
    # ------------------------------------------------------------------

    def _migrate_schema(self) -> None:
        """Add missing columns for backward compatibility with older schemas."""
        # Columns that might be missing from older schemas
        new_columns = [
            ("character_pack_id", "TEXT"),
            ("last_interaction", "TEXT"),
            ("reconnect_count", "INTEGER DEFAULT 0"),
            ("foreground_priority", "INTEGER DEFAULT 0"),
            ("heartbeat_timeout", "REAL DEFAULT 30.0"),
            ("last_heartbeat", "TEXT"),
            ("is_healthy", "INTEGER DEFAULT 1"),
        ]

        for col_name, col_type in new_columns:
            try:
                self._conn.execute(
                    f"ALTER TABLE devices ADD COLUMN {col_name} {col_type}"
                )
                self._conn.commit()
            except sqlite3.OperationalError:
                # Column already exists
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _safe_get(self, row: sqlite3.Row, key: str, default=None):
        """Safely get a column from a sqlite3.Row, returning default if not present."""
        try:
            return row[key]
        except (IndexError, KeyError):
            return default

    def _row_to_info(self, row: sqlite3.Row) -> DeviceInfo:
        """Convert a DB row (sqlite3.Row) to a DeviceInfo instance."""
        return DeviceInfo(
            device_id=row["device_id"],
            device_type=row["device_type"],
            session_id=row["session_id"] or "",
            connected_at=str_to_dt(row["connected_at"]) or datetime.now(timezone.utc),
            last_seen=str_to_dt(row["last_seen"]) or datetime.now(timezone.utc),
            capabilities=json.loads(row["capabilities_json"] or "{}"),
            resume_token=row["resume_token"],
            nonce=row["nonce"],
            state=json.loads(row["state_json"] or "{}"),
            audio_cache_bytes=row["audio_cache_bytes"] or 0,
            muted_until=str_to_dt(row["muted_until"]),
            character_pack_id=self._safe_get(row, "character_pack_id"),
            last_interaction=str_to_dt(self._safe_get(row, "last_interaction")),
            reconnect_count=self._safe_get(row, "reconnect_count", 0),
            foreground_priority=self._safe_get(row, "foreground_priority", 0),
            heartbeat_timeout=self._safe_get(row, "heartbeat_timeout", 30.0),
            last_heartbeat=str_to_dt(self._safe_get(row, "last_heartbeat")),
            is_healthy=bool(self._safe_get(row, "is_healthy", 1)),
        )
