"""Heartbeat monitoring for device health."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from utils import utcnow

if TYPE_CHECKING:
    from registry.service import RegistryService

logger = logging.getLogger("registry.heartbeat")


class HeartbeatMonitor:
    """Monitors device health via heartbeat messages.

    Runs a background task that periodically checks if connected devices
    have sent heartbeats within the expected timeout window. Devices
    that miss heartbeats are marked unhealthy.

    Parameters
    ----------
    registry : RegistryService
        The registry service for device management.
    event_bus : EventBus
        For emitting health events.
    check_interval : float
        Interval in seconds between health checks (default 10.0).
    """

    def __init__(
        self,
        registry: "RegistryService",
        event_bus: Any,  # EventBus type
        check_interval: float = 10.0,
    ) -> None:
        self._registry = registry
        self._event_bus = event_bus
        self._check_interval = check_interval
        self._task: asyncio.Task | None = None
        self._cancelled = False

        # Track last heartbeat time per device
        self._heartbeats: dict[str, datetime] = {}

        # Track unhealthy devices to avoid repeated events
        self._unhealthy_devices: set[str] = set()

    async def start(self) -> None:
        """Start the heartbeat monitoring background task."""
        if self._task is not None and not self._task.done():
            logger.warning("HeartbeatMonitor already started")
            return

        self._cancelled = False
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("HeartbeatMonitor started with check_interval=%.1fs", self._check_interval)

    async def stop(self) -> None:
        """Stop the heartbeat monitoring task."""
        self._cancelled = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("HeartbeatMonitor stopped")

    async def _monitor_loop(self) -> None:
        """Background loop that checks device health periodically."""
        while not self._cancelled:
            try:
                await asyncio.sleep(self._check_interval)
                if not self._cancelled:
                    self.check_health()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Error in heartbeat monitor loop: %s", exc)

    def record_heartbeat(self, device_id: str) -> None:
        """Record a heartbeat from a device.

        Resets the device to healthy state.

        Parameters
        ----------
        device_id : str
            The device that sent a heartbeat.
        """
        self._heartbeats[device_id] = utcnow()

        # Remove from unhealthy set and mark healthy
        if device_id in self._unhealthy_devices:
            self._unhealthy_devices.discard(device_id)
            self.mark_healthy(device_id)

        logger.debug("heartbeat recorded: device_id=%r", device_id)

    def check_health(self) -> None:
        """Check health of all tracked devices.

        Devices that haven't sent a heartbeat within their timeout
        window are marked unhealthy.
        """
        now = utcnow()

        for device_id, last_heartbeat in list(self._heartbeats.items()):
            # Get device info for timeout setting
            info = self._registry._store.get_device(device_id) if self._registry._store else None
            timeout = info.heartbeat_timeout if info else 30.0

            elapsed = (now - last_heartbeat).total_seconds()
            if elapsed > timeout and device_id not in self._unhealthy_devices:
                self.mark_unhealthy(device_id)
                logger.warning(
                    "device unhealthy (heartbeat timeout): device_id=%r elapsed=%.1fs timeout=%.1fs",
                    device_id,
                    elapsed,
                    timeout,
                )

    def mark_unhealthy(self, device_id: str) -> None:
        """Mark a device as unhealthy and emit event.

        Parameters
        ----------
        device_id : str
            The device to mark unhealthy.
        """
        if device_id in self._unhealthy_devices:
            return

        self._unhealthy_devices.add(device_id)
        self._heartbeats.pop(device_id, None)

        # Update registry
        if self._registry and self._registry._store:
            info = self._registry._store.get_device(device_id)
            if info:
                info.is_healthy = False
                info.last_heartbeat = self._heartbeats.get(device_id)
                self._registry._store.upsert_device(info)

        self._event_bus.emit("registry.device_unhealthy", device_id, {
            "device_id": device_id,
        })
        logger.info("device marked unhealthy: device_id=%r", device_id)

    def mark_healthy(self, device_id: str) -> None:
        """Mark a device as healthy.

        Parameters
        ----------
        device_id : str
            The device to mark healthy.
        """
        # Remove from unhealthy set
        self._unhealthy_devices.discard(device_id)

        # Update registry
        if self._registry and self._registry._store:
            info = self._registry._store.get_device(device_id)
            if info:
                info.is_healthy = True
                self._registry._store.upsert_device(info)

        logger.info("device marked healthy: device_id=%r", device_id)

    def remove_device(self, device_id: str) -> None:
        """Remove a device from heartbeat tracking.

        Parameters
        ----------
        device_id : str
            The device to remove.
        """
        self._heartbeats.pop(device_id, None)
        self._unhealthy_devices.discard(device_id)
        logger.debug("device removed from heartbeat tracking: device_id=%r", device_id)

    def get_last_heartbeat(self, device_id: str) -> datetime | None:
        """Get the last heartbeat time for a device.

        Parameters
        ----------
        device_id : str
            The device to query.

        Returns
        -------
        datetime | None
            The last heartbeat time, or None.
        """
        return self._heartbeats.get(device_id)

    def is_device_tracked(self, device_id: str) -> bool:
        """Check if a device is being tracked for heartbeats.

        Parameters
        ----------
        device_id : str
            The device to check.

        Returns
        -------
        bool
            True if device is tracked.
        """
        return device_id in self._heartbeats

    def is_device_unhealthy(self, device_id: str) -> bool:
        """Check if a device is marked unhealthy.

        Parameters
        ----------
        device_id : str
            The device to check.

        Returns
        -------
        bool
            True if device is unhealthy.
        """
        return device_id in self._unhealthy_devices

    @property
    def tracked_devices(self) -> list[str]:
        """Get list of devices currently being tracked.

        Returns
        -------
        list[str]
            List of device IDs being monitored.
        """
        return list(self._heartbeats.keys())
