"""Multi-device management and load balancing.

This module provides:
- Device affinity and preference management
- Load balancing across devices
- Multi-device coordination
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from datp.events import EventBus, get_event_bus

logger = logging.getLogger(__name__)


def _rank_device_loads(
    device_ids: list[str],
    load_by_device: dict[str, DeviceLoad],
    max_load: float,
) -> list[tuple[str, float]]:
    """Return eligible devices ranked from lowest to highest load."""
    candidates: list[tuple[str, float]] = []
    for device_id in device_ids:
        load = load_by_device.get(device_id)
        if load is None:
            candidates.append((device_id, 0.0))
        elif load.total_load < max_load:
            candidates.append((device_id, load.total_load))
    candidates.sort(key=lambda candidate: candidate[1])
    return candidates


# Event types for multi-device operations
MULTI_DEVICE_DEVICE_ADDED = "multi_device.device_added"
MULTI_DEVICE_DEVICE_REMOVED = "multi_device.device_removed"
MULTI_DEVICE_AFFINITY_CHANGED = "multi_device.affinity_changed"
MULTI_DEVICE_LOAD_BALANCED = "multi_device.load_balanced"
MULTI_DEVICE_GROUP_CHANGED = "multi_device.group_changed"


class LoadBalanceStrategy(Enum):
    """Strategy for load balancing across devices."""

    ROUND_ROBIN = "round_robin"  # Even distribution
    LEAST_LOADED = "least_loaded"  # Device with least load
    WEIGHTED = "weighted"  # Weighted by capacity
    AFFINITY = "affinity"  # Prefer device with affinity
    RANDOM = "random"  # Random selection


@dataclass
class DeviceAffinity:
    """Affinity between devices or between device and user."""

    source_id: str  # The device or user
    target_id: str  # The preferred device
    strength: float = 1.0  # 0.0 to 1.0, higher = stronger
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None
    reason: str = ""


@dataclass
class DeviceGroup:
    """A named group of devices for logical operations."""

    group_id: str
    name: str
    description: str = ""
    device_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.device_ids)

    def add_device(self, device_id: str) -> bool:
        """Add device to group. Returns True if added."""
        if device_id not in self.device_ids:
            self.device_ids.append(device_id)
            return True
        return False

    def remove_device(self, device_id: str) -> bool:
        """Remove device from group. Returns True if removed."""
        if device_id in self.device_ids:
            self.device_ids.remove(device_id)
            return True
        return False


@dataclass
class DeviceLoad:
    """Load metrics for a device."""

    device_id: str
    active_operations: int = 0
    queued_operations: int = 0
    cpu_load: float = 0.0  # 0.0 to 1.0
    memory_load: float = 0.0  # 0.0 to 1.0
    network_load: float = 0.0  # 0.0 to 1.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total_load(self) -> float:
        """Combined load metric."""
        return (self.cpu_load + self.memory_load + self.network_load) / 3.0


@dataclass
class LoadBalancerConfig:
    """Configuration for load balancer."""

    strategy: LoadBalanceStrategy = LoadBalanceStrategy.LEAST_LOADED
    max_load_threshold: float = 0.9  # Reject if device above this
    min_load_threshold: float = 0.1  # Prefer if device below this
    affinity_weight: float = 0.3  # Weight for affinity in selection
    enable_failover: bool = True  # Enable automatic failover
    failover_timeout: float = 30.0  # Seconds before failover


class LoadBalancer:
    """Load balancer for distributing work across devices."""

    def __init__(self, config: LoadBalancerConfig | None = None) -> None:
        self._config = config or LoadBalancerConfig()
        self._device_loads: dict[str, DeviceLoad] = {}
        self._round_robin_index: dict[str, int] = {}  # Per-group index

    def update_load(self, device_id: str, load: DeviceLoad) -> None:
        """Update load metrics for a device."""
        self._device_loads[device_id] = load

    def get_load(self, device_id: str) -> DeviceLoad | None:
        """Get current load for a device."""
        return self._device_loads.get(device_id)

    def select_device(
        self,
        device_ids: list[str],
        affinities: dict[str, list[DeviceAffinity]] | None = None,
        preferred_device: str | None = None,
    ) -> str | None:
        """Select the best device for the operation.

        Parameters
        ----------
        device_ids : list[str]
            Available device IDs.
        affinities : dict, optional
            Mapping of source to list of affinities.
        preferred_device : str, optional
            Explicitly preferred device.

        Returns
        -------
        str or None
            Selected device ID, or None if no suitable device.
        """
        if not device_ids:
            return None

        # Check preferred device first
        if preferred_device and preferred_device in device_ids:
            load = self._device_loads.get(preferred_device)
            if load is None or load.total_load < self._config.max_load_threshold:
                return preferred_device

        if self._config.strategy == LoadBalanceStrategy.ROUND_ROBIN:
            return self._round_robin_select(device_ids)

        elif self._config.strategy == LoadBalanceStrategy.LEAST_LOADED:
            return self._least_loaded_select(device_ids)

        elif self._config.strategy == LoadBalanceStrategy.WEIGHTED:
            return self._weighted_select(device_ids)

        elif self._config.strategy == LoadBalanceStrategy.AFFINITY:
            return self._affinity_select(device_ids, affinities)

        elif self._config.strategy == LoadBalanceStrategy.RANDOM:
            import random
            return random.choice(device_ids)

        # Default: least loaded
        return self._least_loaded_select(device_ids)

    def _round_robin_select(self, device_ids: list[str]) -> str | None:
        """Round-robin selection."""
        group_key = ",".join(sorted(device_ids))

        # Initialize index if needed
        if group_key not in self._round_robin_index:
            self._round_robin_index[group_key] = 0

        index = self._round_robin_index[group_key]
        selected = device_ids[index % len(device_ids)]

        # Advance for next time
        self._round_robin_index[group_key] = (index + 1) % len(device_ids)

        return selected

    def _least_loaded_select(self, device_ids: list[str]) -> str | None:
        """Select device with lowest load."""
        candidates = _rank_device_loads(
            device_ids,
            self._device_loads,
            self._config.max_load_threshold,
        )
        if not candidates:
            return None
        return candidates[0][0]

    def _weighted_select(self, device_ids: list[str]) -> str | None:
        """Weighted selection based on available capacity."""
        candidates = []
        for device_id in device_ids:
            load = self._device_loads.get(device_id)
            if load is None:
                capacity = 1.0  # Unknown = assume full capacity
            else:
                capacity = 1.0 - load.total_load

            if capacity > (1.0 - self._config.max_load_threshold):
                candidates.append((device_id, capacity))

        if not candidates:
            return None

        # Weight by capacity
        total = sum(c[1] for c in candidates)
        import random
        r = random.random() * total
        cumulative = 0.0
        for device_id, capacity in candidates:
            cumulative += capacity
            if r <= cumulative:
                return device_id

        return candidates[-1][0]

    def _affinity_select(
        self,
        device_ids: list[str],
        affinities: dict[str, list[DeviceAffinity]] | None,
    ) -> str | None:
        """Select based on affinity preference."""
        if not affinities:
            return self._least_loaded_select(device_ids)

        # Find device with strongest affinity
        best_device = None
        best_strength = -1.0

        for device_id in device_ids:
            device_affinities = affinities.get(device_id, [])
            for affinity in device_affinities:
                if affinity.target_id in device_ids:
                    weighted_strength = affinity.strength * (1.0 - self._config.affinity_weight)
                    if weighted_strength > best_strength:
                        best_strength = weighted_strength
                        best_device = device_id

        # If we found a strong affinity, use it
        if best_device and best_strength > 0.5:
            return best_device

        # Fall back to least loaded
        return self._least_loaded_select(device_ids)


# Singleton instance
_multi_device_manager: "MultiDeviceManager | None" = None


def get_multi_device_manager() -> "MultiDeviceManager":
    """Return the singleton MultiDeviceManager instance."""
    global _multi_device_manager
    if _multi_device_manager is None:
        _multi_device_manager = MultiDeviceManager()
    return _multi_device_manager


def reset_multi_device_manager() -> None:
    """Reset the singleton (for testing)."""
    global _multi_device_manager
    _multi_device_manager = None


class MultiDeviceManager:
    """Manager for multiple device operations.

    Handles:
    - Device affinity and preferences
    - Load balancing across devices
    - Device grouping
    - Multi-device coordination
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        get_current_time: Callable[[], datetime] | None = None,
    ) -> None:
        self._event_bus = event_bus or get_event_bus()
        self._get_time = get_current_time or (lambda: datetime.now(timezone.utc))

        # Device affinity: source_id -> list of affinities
        self._affinities: dict[str, list[DeviceAffinity]] = {}

        # Device groups
        self._groups: dict[str, DeviceGroup] = {}

        # Load balancer
        self._load_balancer = LoadBalancer()

        # Device load tracking
        self._device_loads: dict[str, DeviceLoad] = {}

    # -------------------------------------------------------------------------
    # Affinity Management
    # -------------------------------------------------------------------------

    def set_affinity(
        self,
        source_id: str,
        target_id: str,
        strength: float = 1.0,
        reason: str = "",
        expires_seconds: float | None = None,
    ) -> DeviceAffinity:
        """Set affinity from source to target device.

        Parameters
        ----------
        source_id : str
            The source (device or user) that has affinity.
        target_id : str
            The target device.
        strength : float
            Affinity strength (0.0 to 1.0).
        reason : str
            Reason for affinity.
        expires_seconds : float, optional
            Expiry time in seconds.

        Returns
        -------
        DeviceAffinity
            The created affinity.
        """
        now = self._get_time()
        expires_at = None
        if expires_seconds:
            from datetime import timedelta
            expires_at = now + timedelta(seconds=expires_seconds)

        affinity = DeviceAffinity(
            source_id=source_id,
            target_id=target_id,
            strength=strength,
            reason=reason,
            expires_at=expires_at,
        )

        # Add to affinities
        if source_id not in self._affinities:
            self._affinities[source_id] = []
        else:
            # Remove existing affinity to same target
            self._affinities[source_id] = [
                a for a in self._affinities[source_id]
                if a.target_id != target_id
            ]

        self._affinities[source_id].append(affinity)

        self._event_bus.emit(MULTI_DEVICE_AFFINITY_CHANGED, source_id, {
            "source_id": source_id,
            "target_id": target_id,
            "strength": strength,
            "reason": reason,
        })

        logger.info(
            "affinity set: source=%s target=%s strength=%.2f",
            source_id,
            target_id,
            strength,
        )

        return affinity

    def get_affinities(self, source_id: str) -> list[DeviceAffinity]:
        """Get all affinities for a source."""
        return self._affinities.get(source_id, [])

    def get_affinity_for_target(
        self,
        source_id: str,
        target_id: str,
    ) -> DeviceAffinity | None:
        """Get affinity from source to target."""
        for affinity in self._affinities.get(source_id, []):
            if affinity.target_id == target_id:
                return affinity
        return None

    def remove_affinity(self, source_id: str, target_id: str) -> bool:
        """Remove affinity from source to target."""
        if source_id in self._affinities:
            before = len(self._affinities[source_id])
            self._affinities[source_id] = [
                a for a in self._affinities[source_id]
                if a.target_id != target_id
            ]
            return len(self._affinities[source_id]) < before
        return False

    def get_best_device_for_task(
        self,
        task_type: str,
        available_devices: list[str],
        user_id: str | None = None,
    ) -> str | None:
        """Get the best device for a task based on affinities and load.

        Parameters
        ----------
        task_type : str
            Type of task (e.g., "voice_input", "display", "sensor").
        available_devices : list[str]
            List of available device IDs.
        user_id : str, optional
            User ID for affinity lookup.

        Returns
        -------
        str or None
            Best device ID, or None if no suitable device.
        """
        # Build affinity map for this request
        affinities: dict[str, list[DeviceAffinity]] = {}

        # Add user affinities if provided
        if user_id and user_id in self._affinities:
            affinities[user_id] = self._affinities[user_id]

        # Add device-to-device affinities
        for device_id in available_devices:
            if device_id in self._affinities:
                affinities[device_id] = self._affinities[device_id]

        return self._load_balancer.select_device(
            available_devices,
            affinities,
        )

    # -------------------------------------------------------------------------
    # Group Management
    # -------------------------------------------------------------------------

    def create_group(
        self,
        group_id: str,
        name: str,
        description: str = "",
        device_ids: list[str] | None = None,
    ) -> DeviceGroup:
        """Create a new device group."""
        group = DeviceGroup(
            group_id=group_id,
            name=name,
            description=description,
            device_ids=device_ids or [],
        )
        self._groups[group_id] = group

        self._event_bus.emit(MULTI_DEVICE_GROUP_CHANGED, group_id, {
            "action": "created",
            "group_id": group_id,
            "name": name,
            "device_ids": device_ids,
        })

        logger.info("device group created: group_id=%s name=%s", group_id, name)
        return group

    def get_group(self, group_id: str) -> DeviceGroup | None:
        """Get a group by ID."""
        return self._groups.get(group_id)

    def get_all_groups(self) -> list[DeviceGroup]:
        """Get all device groups."""
        return list(self._groups.values())

    def add_to_group(self, group_id: str, device_id: str) -> bool:
        """Add a device to a group."""
        group = self._groups.get(group_id)
        if group is None:
            return False

        added = group.add_device(device_id)
        if added:
            self._event_bus.emit(MULTI_DEVICE_GROUP_CHANGED, group_id, {
                "action": "device_added",
                "group_id": group_id,
                "device_id": device_id,
            })
        return added

    def remove_from_group(self, group_id: str, device_id: str) -> bool:
        """Remove a device from a group."""
        group = self._groups.get(group_id)
        if group is None:
            return False

        removed = group.remove_device(device_id)
        if removed:
            self._event_bus.emit(MULTI_DEVICE_GROUP_CHANGED, group_id, {
                "action": "device_removed",
                "group_id": group_id,
                "device_id": device_id,
            })
        return removed

    def delete_group(self, group_id: str) -> bool:
        """Delete a group."""
        if group_id in self._groups:
            del self._groups[group_id]
            self._event_bus.emit(MULTI_DEVICE_GROUP_CHANGED, group_id, {
                "action": "deleted",
                "group_id": group_id,
            })
            return True
        return False

    def get_groups_for_device(self, device_id: str) -> list[DeviceGroup]:
        """Get all groups containing a device."""
        return [g for g in self._groups.values() if device_id in g.device_ids]

    # -------------------------------------------------------------------------
    # Load Management
    # -------------------------------------------------------------------------

    def update_device_load(
        self,
        device_id: str,
        active_operations: int = 0,
        queued_operations: int = 0,
        cpu_load: float = 0.0,
        memory_load: float = 0.0,
        network_load: float = 0.0,
    ) -> None:
        """Update load metrics for a device."""
        load = DeviceLoad(
            device_id=device_id,
            active_operations=active_operations,
            queued_operations=queued_operations,
            cpu_load=cpu_load,
            memory_load=memory_load,
            network_load=network_load,
            last_updated=self._get_time(),
        )
        self._device_loads[device_id] = load
        self._load_balancer.update_load(device_id, load)

    def get_device_load(self, device_id: str) -> DeviceLoad | None:
        """Get load metrics for a device."""
        return self._device_loads.get(device_id)

    def get_all_loads(self) -> dict[str, DeviceLoad]:
        """Get load metrics for all tracked devices."""
        return dict(self._device_loads)

    def get_least_loaded_device(
        self,
        device_ids: list[str],
        max_load: float = 0.9,
    ) -> str | None:
        """Get the device with lowest load from a list."""
        candidates = _rank_device_loads(device_ids, self._device_loads, max_load)
        if not candidates:
            return None
        return candidates[0][0]

    # -------------------------------------------------------------------------
    # Multi-Device Operations
    # -------------------------------------------------------------------------

    def distribute_task(
        self,
        task_id: str,
        device_ids: list[str],
        task_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Distribute a task across multiple devices.

        Returns a mapping of device_id to task result.
        """
        results = {}
        for device_id in device_ids:
            # In a real implementation, this would send to each device
            results[device_id] = {
                "status": "dispatched",
                "task_id": task_id,
                "device_id": device_id,
            }

        self._event_bus.emit(MULTI_DEVICE_LOAD_BALANCED, task_id, {
            "task_id": task_id,
            "device_ids": device_ids,
            "results": results,
        })

        return results

    def broadcast_to_group(
        self,
        group_id: str,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        """Broadcast a message to all devices in a group."""
        group = self._groups.get(group_id)
        if group is None:
            return {"error": f"Group not found: {group_id}"}

        results = {}
        for device_id in group.device_ids:
            results[device_id] = {"status": "sent", "message": message}

        return results

    def get_state_summary(self) -> dict[str, Any]:
        """Get a summary of multi-device state."""
        return {
            "affinity_count": sum(len(a) for a in self._affinities.values()),
            "group_count": len(self._groups),
            "tracked_devices": len(self._device_loads),
            "groups": [
                {
                    "group_id": g.group_id,
                    "name": g.name,
                    "device_count": g.size,
                }
                for g in self._groups.values()
            ],
            "load_balancer_strategy": self._load_balancer._config.strategy.value,
        }