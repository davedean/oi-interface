"""RegistryService — the main interface to the device registry."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from datp.events import EventBus
from utils import utcnow

from registry.events import (
    REGISTRY_DEVICE_ONLINE,
    REGISTRY_DEVICE_OFFLINE,
    REGISTRY_STATE_UPDATED,

    REGISTRY_DEVICE_RECONNECTED,
)
from registry.models import DeviceInfo
from registry.store import DeviceStore

logger = logging.getLogger(__name__)


class RegistryService:
    """Tracks all known devices, their capabilities, and their online state.

    The service is backed by :class:`DeviceStore` (SQLite) for persistence and
    maintains an in-memory presence map for fast online/offline queries.
    All store mutations go through async wrappers so they do not block the
    asyncio event loop.

    Parameters
    ----------
    store : DeviceStore
        SQLite persistence layer.
    event_bus : EventBus
        Internal event bus used to emit registry events.
    """

    def __init__(self, store: DeviceStore, event_bus: EventBus) -> None:
        self._store = store
        self._event_bus = event_bus
        # In-memory online/offline map (separate from DB for fast queries)
        self._online: dict[str, bool] = {}

        # Import here to avoid circular dependency issues
        from registry.reconnection import ReconnectionManager
        from registry.heartbeat import HeartbeatMonitor

        self._reconnection = ReconnectionManager(event_bus)
        self._heartbeat = HeartbeatMonitor(self, event_bus)

    async def start(self) -> None:
        """Start the registry service (starts background tasks)."""
        await self._heartbeat.start()
        logger.info("RegistryService started")

    async def stop(self) -> None:
        """Stop the registry service (stops background tasks)."""
        await self._heartbeat.stop()
        logger.info("RegistryService stopped")

    # ------------------------------------------------------------------
    # Mutations — called by DATPServer
    # ------------------------------------------------------------------

    async def device_registered(
        self,
        device_id: str,
        device_type: str,
        session_id: str,
        capabilities: dict[str, Any],
        resume_token: str | None,
        nonce: str | None,
        state: dict[str, Any] | None = None,
    ) -> DeviceInfo:
        """Register or update a device after a successful hello handshake.

        Creates a new ``DeviceInfo`` entry, persists it to SQLite, marks the
        device as online, and emits ``registry.device_online``.

        On reconnect, restores saved state and validates capabilities.
        """
        now = utcnow()

        # Check if this is a reconnect (device was previously known)
        existing_info = self._store.get_device(device_id)
        is_reconnect = existing_info is not None and existing_info.session_id != ""

        if is_reconnect:
            # Record the reconnection
            self._reconnection.record_reconnect(device_id)
            logger.info(
                "device reconnected: device_id=%r type=%r previous_session=%r",
                device_id,
                device_type,
                existing_info.session_id,
            )

            # Validate capabilities on reconnect
            cap_diff = self.validate_capabilities_on_reconnect(device_id, capabilities)
            if cap_diff["removed"] or cap_diff["changed"]:
                logger.warning(
                    "device capabilities changed on reconnect: device_id=%r diff=%r",
                    device_id,
                    cap_diff,
                )

        # Restore saved state if available
        saved_state = self._reconnection.restore_state(device_id)
        if saved_state is not None:
            # Merge saved state with new state (new state takes precedence for keys that exist in both)
            merged_state = {**saved_state, **(state or {})}
            state = merged_state

        # Get existing reconnect count
        reconnect_count = 0
        foreground_priority = 0
        heartbeat_timeout = 30.0
        last_interaction = None

        if existing_info:
            reconnect_count = existing_info.reconnect_count
            foreground_priority = existing_info.foreground_priority
            heartbeat_timeout = existing_info.heartbeat_timeout
            last_interaction = existing_info.last_interaction

        # If this was a reconnect, increment the count
        if is_reconnect:
            reconnect_count = self._reconnection.get_reconnect_count(device_id)

        info = DeviceInfo(
            device_id=device_id,
            device_type=device_type,
            session_id=session_id,
            connected_at=now,
            last_seen=now,
            capabilities=capabilities,
            resume_token=resume_token,
            nonce=nonce,
            state=state or {},
            audio_cache_bytes=0,
            muted_until=None,
            reconnect_count=reconnect_count,
            foreground_priority=foreground_priority,
            heartbeat_timeout=heartbeat_timeout,
            last_interaction=last_interaction,
            is_healthy=True,
        )
        await self._store.upsert_device_async(info)
        self._online[device_id] = True

        # Record heartbeat for new device
        self._heartbeat.record_heartbeat(device_id)

        if is_reconnect:
            self._event_bus.emit(REGISTRY_DEVICE_RECONNECTED, device_id, {
                "device_id": device_id,
                "device_type": device_type,
                "session_id": session_id,
                "reconnect_count": reconnect_count,
                "capabilities_diff": cap_diff if is_reconnect else None,
            })
        else:
            self._event_bus.emit(REGISTRY_DEVICE_ONLINE, device_id, {
                "device_id": device_id,
                "device_type": device_type,
                "session_id": session_id,
            })

        logger.info(
            "%s: device_id=%r type=%r reconnect_count=%d",
            "device reconnected" if is_reconnect else "device online",
            device_id,
            device_type,
            reconnect_count,
        )
        return info

    def device_disconnected(self, device_id: str) -> None:
        """Mark a device as offline (fire-and-forget).

        Keeps the entry in SQLite so it remains queryable; emits
        ``registry.device_offline``. Idempotent: if the device is already
        offline this is a no-op, preventing stale finalizers from racing
        with a fast reconnect.

        This method is synchronous so that DATPServer's finally block can
        call it without awaiting. The async DB work is scheduled via
        asyncio.create_task so it does not block the caller.
        """
        if not self._online.get(device_id, False):
            return  # already offline

        self._online[device_id] = False

        # Record disconnect for reconnection tracking
        self._reconnection.record_disconnect(device_id)

        # Save state for recovery on reconnect
        info = self._store.get_device(device_id)
        if info is not None:
            self._reconnection.save_state(device_id, info.state)

        # Remove from heartbeat tracking
        self._heartbeat.remove_device(device_id)

        # Schedule async work without blocking the caller.
        asyncio.create_task(self._store.device_seen_async(device_id))

        self._event_bus.emit(REGISTRY_DEVICE_OFFLINE, device_id, {
            "device_id": device_id,
        })
        logger.info("device offline: device_id=%r", device_id)

    def _mark_online(self, device_id: str) -> None:
        """Mark a device as online without emitting a device_online event.

        Used by DATPServer to safely set the online flag before closing a
        stale WebSocket during a fast reconnect, preventing the old
        connection's finalizer from racing with the new registration.
        """
        self._online[device_id] = True

    async def device_state_update(self, device_id: str, state: dict[str, Any]) -> None:
        """Store a device state report.

        Persists the reported state dict and emits ``registry.state_updated``.
        """
        await self._store.update_state_async(device_id, state)
        await self._store.device_seen_async(device_id)
        self._event_bus.emit(REGISTRY_STATE_UPDATED, device_id, {
            "device_id": device_id,
            "state": state,
        })
        logger.debug("device state updated: device_id=%r mode=%r", device_id, state.get("mode"))

    # ------------------------------------------------------------------
    # Stability features
    # ------------------------------------------------------------------

    async def update_last_interaction(self, device_id: str) -> None:
        """Update the last interaction timestamp for a device.

        Parameters
        ----------
        device_id : str
            The device to update.
        """
        await self._store.update_last_interaction_async(device_id)
        info = await self._store.get_device_async(device_id)
        if info:
            info.last_interaction = utcnow()
        logger.debug("last interaction updated: device_id=%r", device_id)

    async def set_foreground_device(self, device_id: str) -> bool:
        """Set a device as the foreground device.

        Sets its foreground priority higher than all other devices.

        Parameters
        ----------
        device_id : str
            The device to set as foreground.

        Returns
        -------
        bool
            True if successful, False if device not found.
        """
        info = await self._store.get_device_async(device_id)
        if info is None:
            logger.warning("cannot set foreground device: device not found: %r", device_id)
            return False

        if not self._online.get(device_id, False):
            logger.warning("cannot set foreground device: device not online: %r", device_id)
            return False

        await self._store.set_foreground_priority_highest_async(device_id)
        logger.info("foreground device set: device_id=%r", device_id)
        return True

    async def record_heartbeat(self, device_id: str) -> None:
        """Record a heartbeat from a device.

        Parameters
        ----------
        device_id : str
            The device that sent a heartbeat.
        """
        self._heartbeat.record_heartbeat(device_id)
        await self._store.update_heartbeat_async(device_id)

    def validate_capabilities_on_reconnect(
        self, device_id: str, new_caps: dict[str, Any]
    ) -> dict[str, list]:
        """Validate capabilities when a device reconnects.

        Compares the new capabilities with the previously stored capabilities
        and returns a diff showing what was added, removed, or changed.

        Parameters
        ----------
        device_id : str
            The reconnecting device.
        new_caps : dict
            The new capabilities dict.

        Returns
        -------
        dict
            Dict with keys: 'added' (list of new caps), 'removed' (list of missing caps),
            'changed' (list of modified cap keys).
        """
        info = self._store.get_device(device_id)
        if info is None:
            return {"added": list(new_caps.keys()), "removed": [], "changed": []}

        old_caps = info.capabilities or {}

        # Find added capabilities (in new but not in old)
        added = [k for k in new_caps if k not in old_caps]

        # Find removed capabilities (in old but not in new)
        removed = [k for k in old_caps if k not in new_caps]

        # Find changed capabilities (key exists in both but value differs)
        changed = [
            k for k in new_caps
            if k in old_caps and new_caps[k] != old_caps[k]
        ]

        return {
            "added": added,
            "removed": removed,
            "changed": changed,
        }

    def get_health_status(self, device_id: str) -> dict[str, Any] | None:
        """Get health status for a device.

        Parameters
        ----------
        device_id : str
            The device to query.

        Returns
        -------
        dict | None
            Dict with 'is_healthy', 'last_heartbeat', 'heartbeat_timeout',
            or None if device not found.
        """
        info = self._store.get_device(device_id)
        if info is None:
            return None

        return {
            "is_healthy": info.is_healthy,
            "last_heartbeat": info.last_heartbeat.isoformat() if info.last_heartbeat else None,
            "heartbeat_timeout": info.heartbeat_timeout,
            "is_online": self._online.get(device_id, False),
        }

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_device(self, device_id: str) -> DeviceInfo | None:
        """Return the full device record from SQLite, or None."""
        return await self._store.get_device_async(device_id)

    async def get_all_devices(self) -> list[DeviceInfo]:
        """Return all devices (online and offline) from SQLite."""
        return await self._store.get_all_devices_async()

    def get_online_devices(self) -> list[DeviceInfo]:
        """Return only currently connected (online) devices."""
        online_ids = [dev_id for dev_id, is_online in self._online.items() if is_online]
        devices = []
        for dev_id in online_ids:
            # These are sync reads from an already-initialised dict, so safe
            # to call directly here (no asyncio needed).
            info = self._store.get_device(dev_id)
            if info is not None:
                devices.append(info)
        return devices

    def get_capabilities(self, device_id: str) -> dict | None:
        """Return the capabilities dict for a device, or None."""
        info = self._store.get_device(device_id)
        if info is None:
            return None
        return info.capabilities

    def get_foreground_device(self) -> DeviceInfo | None:
        """Return the primary / foreground device.

        Selection logic:
        1. If any online device has foreground_priority > 0, select highest priority
        2. Tiebreak by last_interaction (most recent wins)
        3. If no priority set, fallback to single-device logic
        """
        online = self.get_online_devices()
        if not online:
            return None

        # Filter to devices with priority set
        priority_devices = [d for d in online if d.foreground_priority > 0]

        if priority_devices:
            # Sort by priority (descending), then by last_interaction (descending)
            priority_devices.sort(
                key=lambda d: (d.foreground_priority, d.last_interaction or datetime.min),
                reverse=True,
            )
            return priority_devices[0]

        # Fallback: single device wins, tiebreak by last_interaction
        if len(online) == 1:
            return online[0]

        # Multiple devices, no priority - use most recent interaction
        online_with_interaction = [d for d in online if d.last_interaction is not None]
        if online_with_interaction:
            online_with_interaction.sort(key=lambda d: d.last_interaction, reverse=True)
            return online_with_interaction[0]

        return None

    # ------------------------------------------------------------------
    # Character Pack Assignment
    # ------------------------------------------------------------------

    async def set_character_pack(self, device_id: str, character_pack_id: str | None) -> bool:
        """Set or clear the character pack for a device.

        Parameters
        ----------
        device_id : str
            The device to assign the character pack to.
        character_pack_id : str or None
            The pack_id to assign, or None to clear.

        Returns
        -------
        bool
            True if the device was found and updated, False otherwise.
        """
        result = await self._store.set_character_pack_async(device_id, character_pack_id)
        if result:
            logger.info("character pack set: device_id=%r pack_id=%r", device_id, character_pack_id)
        return result

    async def get_character_pack(self, device_id: str) -> str | None:
        """Get the character pack assigned to a device.

        Returns the pack_id or None if not set.
        """
        info = await self._store.get_device_async(device_id)
        if info is None:
            return None
        return info.character_pack_id

    @property
    def online_count(self) -> int:
        """Number of currently connected devices."""
        return sum(1 for v in self._online.values() if v)

    @property
    def heartbeat_monitor(self):
        """Access the heartbeat monitor for testing."""
        return self._heartbeat

    @property
    def reconnection_manager(self):
        """Access the reconnection manager for testing."""
        return self._reconnection
