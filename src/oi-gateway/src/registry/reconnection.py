"""Reconnection management with exponential backoff and state recovery."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime
from typing import TYPE_CHECKING, Any

from utils import utcnow

if TYPE_CHECKING:
    from datp.events import EventBus

logger = logging.getLogger("registry.reconnection")


class ReconnectionManager:
    """Tracks reconnection state and provides exponential backoff for devices.

    Manages device disconnection/reconnection tracking, backoff delays for
    reconnection attempts, and state preservation for recovery on reconnect.

    Parameters
    ----------
    event_bus : EventBus
        For emitting reconnection events.
    """

    def __init__(
        self,
        event_bus: "EventBus",
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        max_retries: int = 10,
        jitter: bool = True,
    ) -> None:
        self._event_bus = event_bus
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._max_retries = max_retries
        self._jitter = jitter

        # Track disconnection times
        self._disconnect_times: dict[str, datetime] = {}
        # Track reconnection attempt counts (cumulative)
        self._reconnect_counts: dict[str, int] = {}
        # Saved state for recovery on reconnect
        self._saved_states: dict[str, dict[str, Any]] = {}

    def record_disconnect(self, device_id: str) -> None:
        """Record a device disconnection and increment reconnection count.

        Parameters
        ----------
        device_id : str
            The device that disconnected.
        """
        self._disconnect_times[device_id] = utcnow()
        self._reconnect_counts[device_id] = self._reconnect_counts.get(device_id, 0) + 1
        logger.debug(
            "device disconnect recorded: device_id=%r reconnect_count=%d",
            device_id,
            self._reconnect_counts[device_id],
        )

    def record_reconnect(self, device_id: str) -> None:
        """Record a device reconnection and emit event.

        Clears disconnect time but preserves reconnection count for monitoring.

        Parameters
        ----------
        device_id : str
            The device that reconnected.
        """
        self._disconnect_times.pop(device_id, None)
        self._event_bus.emit("registry.device_reconnected", device_id, {
            "device_id": device_id,
            "reconnect_count": self._reconnect_counts.get(device_id, 0),
        })
        logger.info(
            "device reconnected: device_id=%r reconnect_count=%d",
            device_id,
            self._reconnect_counts.get(device_id, 0),
        )

    def get_backoff_delay(self, device_id: str) -> float:
        """Calculate exponential backoff delay for reconnection.

        Uses exponential backoff: min(base_delay * 2^reconnect_count, max_delay)
        with optional jitter for randomization.

        Parameters
        ----------
        device_id : str
            The device requesting a backoff delay.

        Returns
        -------
        float
            Delay in seconds before attempting reconnection.
        """
        count = self._reconnect_counts.get(device_id, 0)
        delay = min(self._base_delay * (2 ** count), self._max_delay)

        if self._jitter and delay > 0:
            # Add jitter up to 10% of the delay
            jitter_amount = secrets.randbelow(int(delay * 100)) / 1000.0
            delay += jitter_amount

        return delay

    def should_reconnect(self, device_id: str) -> bool:
        """Check if reconnection should be attempted for a device.

        Parameters
        ----------
        device_id : str
            The device to check.

        Returns
        -------
        bool
            True if reconnection count is within limits.
        """
        count = self._reconnect_counts.get(device_id, 0)
        return count <= self._max_retries

    def save_state(self, device_id: str, state: dict[str, Any]) -> None:
        """Save device state for recovery on reconnect.

        Parameters
        ----------
        device_id : str
            The device whose state to save.
        state : dict
            The state dict to save.
        """
        if state:
            self._saved_states[device_id] = dict(state)
            logger.debug("state saved for device_id=%r", device_id)

    def restore_state(self, device_id: str) -> dict[str, Any] | None:
        """Restore saved state for a device and clear the saved copy.

        Parameters
        ----------
        device_id : str
            The device whose state to restore.

        Returns
        -------
        dict | None
            The saved state dict, or None if no state was saved.
        """
        state = self._saved_states.pop(device_id, None)
        if state is not None:
            logger.info("state restored for device_id=%r", device_id)
        return state

    def get_reconnect_count(self, device_id: str) -> int:
        """Get the reconnection count for a device.

        Parameters
        ----------
        device_id : str
            The device to query.

        Returns
        -------
        int
            Number of reconnection attempts.
        """
        return self._reconnect_counts.get(device_id, 0)

    def reset_reconnect_count(self, device_id: str) -> None:
        """Reset reconnection count for a device (e.g., after successful session).

        Parameters
        ----------
        device_id : str
            The device whose count to reset.
        """
        self._reconnect_counts[device_id] = 0
        logger.debug("reconnect count reset for device_id=%r", device_id)

    def get_disconnect_time(self, device_id: str) -> datetime | None:
        """Get the last disconnect time for a device.

        Parameters
        ----------
        device_id : str
            The device to query.

        Returns
        -------
        datetime | None
            The disconnect timestamp, or None if not disconnected.
        """
        return self._disconnect_times.get(device_id)

    def clear_device(self, device_id: str) -> None:
        """Clear all reconnection state for a device.

        Parameters
        ----------
        device_id : str
            The device to clear.
        """
        self._disconnect_times.pop(device_id, None)
        self._reconnect_counts.pop(device_id, None)
        self._saved_states.pop(device_id, None)
        logger.debug("all reconnection state cleared for device_id=%r", device_id)
