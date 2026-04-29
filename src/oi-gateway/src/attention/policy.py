"""Attention policy for tracking and managing device attention.

Attention represents which device the user is currently focused on,
distinct from foreground (most recent input device).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from datp.events import EventBus, get_event_bus

from .events import (
    ATTENTION_CHANGED,
    ATTENTION_ACQUIRED,
    ATTENTION_RELEASED,
    ATTENTION_PRIORITY_UPDATED,
    ATTENTION_IDLE,
    ATTENTION_ACTIVE,
)

logger = logging.getLogger(__name__)


class AttentionTransition(Enum):
    """How attention moved between devices."""

    EXPLICIT = "explicit"  # User explicitly focused a device
    IMPLICIT = "implicit"  # Attention moved automatically (e.g., new input)
    TIMEOUT = "timeout"  # Attention timed out, returned to idle
    DEVICE_OFFLINE = "device_offline"  # Attended device went offline
    INTERRUPTED = "interrupted"  # Higher priority event interrupted


# Singleton instance
_attention_policy: "AttentionPolicy | None" = None


def get_attention_policy() -> "AttentionPolicy":
    """Return the singleton AttentionPolicy instance."""
    global _attention_policy
    if _attention_policy is None:
        _attention_policy = AttentionPolicy()
    return _attention_policy


def reset_attention_policy() -> None:
    """Reset the singleton (for testing)."""
    global _attention_policy
    _attention_policy = None


@dataclass
class AttentionState:
    """Current attention state for a device."""

    device_id: str
    state: str = ATTENTION_IDLE  # idle, active, transitioning
    acquired_at: datetime | None = None
    last_activity: datetime | None = None
    auto_release_after_seconds: float | None = None
    priority: int = 0  # Higher = more likely to get attention
    reason: str = ""  # Why attention is in this state


@dataclass
class AttentionConfig:
    """Configuration for attention policy."""

    # How long before attention automatically releases (seconds)
    auto_release_timeout: float = 300.0  # 5 minutes
    # How long before activity timestamp considered stale (seconds)
    activity_timeout: float = 60.0
    # Require explicit attention release (don't auto-release on new input)
    require_explicit_release: bool = False
    # Enable attention priority system
    enable_priority: bool = True
    # Default priority for devices without explicit priority
    default_priority: int = 0


class AttentionPolicy:
    """Policy for managing device attention.

    Attention tracks which device the user is focused on, enabling:
    - Intelligent routing based on user focus
    - Attention-aware notifications
    - Priority-based attention assignment

    Attention is separate from foreground:
    - Foreground: the device that last received input
    - Attention: the device the user is actively looking at/using
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        config: AttentionConfig | None = None,
        get_current_time: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize attention policy.

        Parameters
        ----------
        event_bus : EventBus, optional
            Event bus for emitting attention events.
        config : AttentionConfig, optional
            Attention policy configuration.
        get_current_time : callable, optional
            Function returning current time (for testing).
        """
        self._event_bus = event_bus or get_event_bus()
        self._config = config or AttentionConfig()
        self._get_time = get_current_time or (lambda: datetime.now(timezone.utc))

        # Attention state tracking
        self._device_attention: dict[str, AttentionState] = {}
        self._current_attention: str | None = None  # device_id with attention, or None

        # Priority queue for attention selection
        self._attention_queue: list[str] = []  # Ordered list of device_ids waiting for attention

    @property
    def current_attention(self) -> str | None:
        """The device ID that currently has attention, or None."""
        return self._current_attention

    @property
    def has_attention(self) -> bool:
        """Whether any device currently has attention."""
        return self._current_attention is not None

    def get_attention_state(self, device_id: str) -> AttentionState | None:
        """Get attention state for a specific device.

        Parameters
        ----------
        device_id : str
            The device to query.

        Returns
        -------
        AttentionState or None
            The device's attention state, or None if not tracked.
        """
        return self._device_attention.get(device_id)

    def acquire_attention(
        self,
        device_id: str,
        reason: str = "",
        priority: int | None = None,
        auto_release_seconds: float | None = None,
        transition: AttentionTransition = AttentionTransition.EXPLICIT,
    ) -> bool:
        """Acquire attention for a device.

        Parameters
        ----------
        device_id : str
            The device requesting attention.
        reason : str
            Reason for attention acquisition.
        priority : int, optional
            Override default priority for this attention.
        auto_release_seconds : float, optional
            Auto-release attention after this many seconds.
        transition : AttentionTransition
            How attention is being acquired.

        Returns
        -------
        bool
            True if attention was acquired, False if denied.
        """
        # Check priority - can we overtake current attention? (check BEFORE releasing)
        if self._current_attention and self._current_attention != device_id:
            current_state = self._device_attention.get(self._current_attention)
            new_priority = priority if priority is not None else self._config.default_priority

            if current_state and current_state.priority > new_priority:
                logger.debug(
                    "attention denied: device %s priority %d < current %d",
                    device_id,
                    new_priority,
                    current_state.priority,
                )
                # Queue device for attention when current releases
                self._queue_for_attention(device_id, priority or self._config.default_priority)
                return False

            # If we can overtake, release current attention (if not requiring explicit release)
            if self._config.require_explicit_release:
                # Explicit release required - cannot switch without explicit release
                logger.debug(
                    "attention denied: require_explicit_release is True, current=%s",
                    self._current_attention,
                )
                return False
            else:
                self._release_current_attention(transition=AttentionTransition.IMPLICIT)

        now = self._get_time()

        # Create or update attention state
        state = self._device_attention.get(device_id)
        if state is None:
            state = AttentionState(
                device_id=device_id,
                state=ATTENTION_ACTIVE,
                acquired_at=now,
                priority=priority or self._config.default_priority,
            )
        else:
            state.state = ATTENTION_ACTIVE
            state.acquired_at = now
            state.priority = priority or state.priority

        state.last_activity = now
        state.reason = reason
        state.auto_release_after_seconds = auto_release_seconds

        self._device_attention[device_id] = state
        old_attention = self._current_attention
        self._current_attention = device_id

        # Emit events
        self._emit_attention_event(
            ATTENTION_ACQUIRED,
            device_id,
            {
                "device_id": device_id,
                "reason": reason,
                "previous_attention": old_attention,
                "transition": transition.value,
            },
        )

        if old_attention != device_id:
            self._emit_attention_event(
                ATTENTION_CHANGED,
                device_id,
                {
                    "device_id": device_id,
                    "previous_attention": old_attention,
                    "transition": transition.value,
                    "reason": reason,
                },
            )

        logger.info(
            "attention acquired: device_id=%s reason=%s transition=%s",
            device_id,
            reason,
            transition.value,
        )
        return True

    def release_attention(
        self,
        device_id: str,
        reason: str = "",
        transition: AttentionTransition = AttentionTransition.EXPLICIT,
    ) -> bool:
        """Release attention from a device.

        Parameters
        ----------
        device_id : str
            The device releasing attention.
        reason : str
            Reason for release.
        transition : AttentionTransition
            How attention is being released.

        Returns
        -------
        bool
            True if attention was released, False if device didn't have attention.
        """
        if self._current_attention != device_id:
            return False

        self._release_current_attention(reason=reason, transition=transition)
        return True

    def _release_current_attention(
        self,
        reason: str = "",
        transition: AttentionTransition = AttentionTransition.EXPLICIT,
    ) -> None:
        """Internal method to release current attention."""
        if self._current_attention is None:
            return

        device_id = self._current_attention
        self._current_attention = None

        # Update state to idle
        state = self._device_attention.get(device_id)
        if state:
            state.state = ATTENTION_IDLE
            state.acquired_at = None

        # Emit release event
        self._emit_attention_event(
            ATTENTION_RELEASED,
            device_id,
            {
                "device_id": device_id,
                "reason": reason,
                "transition": transition.value,
            },
        )

        logger.info(
            "attention released: device_id=%s reason=%s transition=%s",
            device_id,
            reason,
            transition.value,
        )

        # Check for queued devices
        self._process_attention_queue()

    def _queue_for_attention(self, device_id: str, priority: int) -> None:
        """Add device to attention queue based on priority."""
        # Remove if already in queue
        if device_id in self._attention_queue:
            self._attention_queue.remove(device_id)

        # Insert by priority (higher priority first)
        inserted = False
        for i, existing in enumerate(self._attention_queue):
            existing_state = self._device_attention.get(existing)
            if existing_state and existing_state.priority < priority:
                self._attention_queue.insert(i, device_id)
                inserted = True
                break

        if not inserted:
            self._attention_queue.append(device_id)

    def _process_attention_queue(self) -> None:
        """Process queued devices and grant attention to highest priority."""
        if not self._attention_queue:
            return

        # Find next valid device (still in device_attention)
        while self._attention_queue:
            device_id = self._attention_queue.pop(0)
            if device_id in self._device_attention:
                # Grant attention
                self.acquire_attention(
                    device_id,
                    reason="queued",
                    transition=AttentionTransition.IMPLICIT,
                )
                break

    def record_activity(
        self,
        device_id: str,
        activity_type: str = "interaction",
    ) -> None:
        """Record user activity on a device.

        This updates the last_activity timestamp and can trigger
        attention acquisition based on configuration.

        Parameters
        ----------
        device_id : str
            The device with activity.
        activity_type : str
            Type of activity (interaction, input, output, etc).
        """
        now = self._get_time()
        state = self._device_attention.get(device_id)
        if state:
            state.last_activity = now
            logger.debug(
                "attention activity recorded: device_id=%s type=%s",
                device_id,
                activity_type,
            )

    def set_priority(
        self,
        device_id: str,
        priority: int,
        reason: str = "",
    ) -> bool:
        """Set attention priority for a device.

        Parameters
        ----------
        device_id : str
            The device to set priority for.
        priority : int
            Priority value (higher = more likely to get attention).
        reason : str
            Reason for priority change.

        Returns
        -------
        bool
            True if priority was set.
        """
        state = self._device_attention.get(device_id)
        old_priority = None
        if state is None:
            state = AttentionState(
                device_id=device_id,
                state=ATTENTION_IDLE,
                priority=priority,
            )
            self._device_attention[device_id] = state
        else:
            old_priority = state.priority
            state.priority = priority

        self._emit_attention_event(
            ATTENTION_PRIORITY_UPDATED,
            device_id,
            {
                "device_id": device_id,
                "priority": priority,
                "previous_priority": old_priority,
                "reason": reason,
            },
        )

        # Re-queue if priority changed
        if device_id in self._attention_queue:
            self._attention_queue.remove(device_id)
            if priority > 0:
                self._queue_for_attention(device_id, priority)

        logger.info(
            "attention priority set: device_id=%s priority=%d",
            device_id,
            priority,
        )
        return True

    def get_attention_candidates(
        self,
        include_current: bool = True,
        min_priority: int | None = None,
    ) -> list[str]:
        """Get list of devices that could receive attention.

        Parameters
        ----------
        include_current : bool
            Include currently attended device in results.
        min_priority : int, optional
            Filter to devices with priority >= this value.

        Returns
        -------
        list[str]
            List of device IDs suitable for attention.
        """
        candidates = []

        for device_id, state in self._device_attention.items():
            if min_priority is not None and state.priority < min_priority:
                continue

            if not include_current and device_id == self._current_attention:
                continue

            candidates.append(device_id)

        # Sort by priority (highest first)
        candidates.sort(
            key=lambda d: self._device_attention[d].priority,
            reverse=True,
        )

        return candidates

    def handle_device_offline(self, device_id: str) -> bool:
        """Handle a device going offline.

        Releases attention if the offline device has it.

        Parameters
        ----------
        device_id : str
            The device that went offline.

        Returns
        -------
        bool
            True if attention was held by this device and was released.
        """
        if self._current_attention == device_id:
            self._release_current_attention(
                reason="device offline",
                transition=AttentionTransition.DEVICE_OFFLINE,
            )
            return True
        return False

    def check_timeouts(self) -> list[str]:
        """Check for attention timeouts and release stale attention.

        Returns
        -------
        list[str]
            List of device IDs whose attention was released due to timeout.
        """
        if not self._config.auto_release_timeout:
            return []

        now = self._get_time()
        released = []

        if self._current_attention:
            state = self._device_attention.get(self._current_attention)
            if state:
                # Check auto-release timeout
                if state.auto_release_after_seconds:
                    elapsed = (now - state.last_activity).total_seconds()
                    if elapsed >= state.auto_release_after_seconds:
                        # Capture device_id BEFORE releasing (release sets current_attention to None)
                        device_id_to_release = self._current_attention
                        self.release_attention(
                            device_id_to_release,
                            reason="timeout",
                            transition=AttentionTransition.TIMEOUT,
                        )
                        released.append(device_id_to_release)

                # Check activity timeout
                elif self._config.activity_timeout and state.last_activity:
                    elapsed = (now - state.last_activity).total_seconds()
                    if elapsed >= self._config.activity_timeout:
                        # Optionally release based on inactivity
                        logger.debug(
                            "attention idle: device_id=%s idle_seconds=%.1f",
                            self._current_attention,
                            elapsed,
                        )

        return released

    def get_state_summary(self) -> dict[str, Any]:
        """Get a summary of current attention state.

        Returns
        -------
        dict
            Summary including current attention, queued devices, etc.
        """
        return {
            "current_attention": self._current_attention,
            "has_attention": self.has_attention,
            "tracked_devices": list(self._device_attention.keys()),
            "attention_queue": list(self._attention_queue),
            "config": {
                "auto_release_timeout": self._config.auto_release_timeout,
                "activity_timeout": self._config.activity_timeout,
                "require_explicit_release": self._config.require_explicit_release,
                "enable_priority": self._config.enable_priority,
            },
        }

    def _emit_attention_event(
        self,
        event_type: str,
        device_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Emit an attention event to the event bus."""
        self._event_bus.emit(event_type, device_id, payload)


# For backward compatibility, also expose the function
def create_attention_policy(
    event_bus: EventBus | None = None,
    config: AttentionConfig | None = None,
) -> AttentionPolicy:
    """Create a new AttentionPolicy instance.

    For testing or when multiple instances are needed.
    """
    return AttentionPolicy(event_bus=event_bus, config=config)