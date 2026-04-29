"""Device clustering and grouping utilities.

This module provides functionality to group devices by various criteria
such as capability, location, device type, and custom attributes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ClusterStrategy(Enum):
    """Strategy for clustering devices."""

    CAPABILITY = "capability"  # Group by capability matching
    LOCATION = "location"  # Group by physical location
    TYPE = "type"  # Group by device type
    CUSTOM = "custom"  # Group by custom attributes
    WEIGHTED = "weighted"  # Multiple factors with weights


@dataclass
class DeviceCluster:
    """A cluster of devices grouped together.

    Clusters represent logical groupings of devices that can be
    treated as a single unit for certain operations.
    """

    cluster_id: str
    name: str
    strategy: ClusterStrategy
    device_ids: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def size(self) -> int:
        """Number of devices in the cluster."""
        return len(self.device_ids)

    @property
    def is_empty(self) -> bool:
        """Whether the cluster has no devices."""
        return len(self.device_ids) == 0

    def add_device(self, device_id: str) -> None:
        """Add a device to this cluster."""
        if device_id not in self.device_ids:
            self.device_ids.append(device_id)

    def remove_device(self, device_id: str) -> bool:
        """Remove a device from this cluster.

        Returns
        -------
        bool
            True if device was found and removed.
        """
        if device_id in self.device_ids:
            self.device_ids.remove(device_id)
            return True
        return False

    def has_device(self, device_id: str) -> bool:
        """Check if a device is in this cluster."""
        return device_id in self.device_ids


def group_by_capability(
    devices: dict[str, dict[str, Any]],
    required_capability: str,
) -> dict[str, list[str]]:
    """Group devices by capability match.

    Parameters
    ----------
    devices : dict
        Dictionary mapping device_id to device capabilities dict.
    required_capability : str
        The capability to match on.

    Returns
    -------
    dict
        Mapping of capability value to list of device IDs.
    """
    groups: dict[str, list[str]] = {}

    for device_id, caps in devices.items():
        cap_value = caps.get(required_capability)
        if cap_value is not None:
            key = str(cap_value)
            if key not in groups:
                groups[key] = []
            groups[key].append(device_id)
        else:
            # Group devices without this capability
            if "none" not in groups:
                groups["none"] = []
            groups["none"].append(device_id)

    return groups


def group_by_location(
    devices: dict[str, dict[str, Any]],
    location_key: str = "location",
) -> dict[str, list[str]]:
    """Group devices by location attribute.

    Parameters
    ----------
    devices : dict
        Dictionary mapping device_id to device info dict.
    location_key : str
        The key in device info that contains location.

    Returns
    -------
    dict
        Mapping of location to list of device IDs.
    """
    groups: dict[str, list[str]] = {"unknown": []}

    for device_id, info in devices.items():
        location = info.get(location_key, "unknown")
        if location not in groups:
            groups[location] = []
        groups[location].append(device_id)

    # Remove empty unknown group
    if not groups["unknown"]:
        del groups["unknown"]

    return groups


def group_by_type(
    devices: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Group devices by device type.

    Parameters
    ----------
    devices : dict
        Dictionary mapping device_id to device info dict.

    Returns
    -------
    dict
        Mapping of device type to list of device IDs.
    """
    groups: dict[str, list[str]] = {"unknown": []}

    for device_id, info in devices.items():
        device_type = info.get("device_type", "unknown")
        if device_type not in groups:
            groups[device_type] = []
        groups[device_type].append(device_id)

    # Remove empty unknown group
    if not groups["unknown"]:
        del groups["unknown"]

    return groups


def cluster_devices(
    devices: list[str],
    info_map: dict[str, dict[str, Any]],
    strategy: ClusterStrategy = ClusterStrategy.TYPE,
    weights: dict[str, float] | None = None,
) -> list[DeviceCluster]:
    """Cluster devices using the specified strategy.

    Parameters
    ----------
    devices : list[str]
        List of device IDs to cluster.
    info_map : dict
        Dictionary mapping device_id to device info/capabilities.
    strategy : ClusterStrategy
        The clustering strategy to use.
    weights : dict, optional
        Weights for weighted clustering (key: attribute, value: weight).

    Returns
    -------
    list[DeviceCluster]
        List of device clusters.
    """
    clusters: list[DeviceCluster] = []

    if strategy == ClusterStrategy.TYPE:
        type_groups = group_by_type(info_map)
        for device_type, device_ids in type_groups.items():
            cluster = DeviceCluster(
                cluster_id=f"type-{device_type}",
                name=f"Type: {device_type}",
                strategy=strategy,
                device_ids=[d for d in device_ids if d in devices],
            )
            if not cluster.is_empty:
                clusters.append(cluster)

    elif strategy == ClusterStrategy.CAPABILITY:
        # Group by primary capability if available
        if not devices:
            return clusters

        # Build a composite key from all capabilities
        cap_groups: dict[str, list[str]] = {}
        for device_id in devices:
            info = info_map.get(device_id, {})
            caps = info.get("capabilities", {})

            # Create a signature from key capabilities
            sig_parts = []
            for key in sorted(caps.keys()):
                val = caps[key]
                if isinstance(val, (str, int, bool)):
                    sig_parts.append(f"{key}={val}")

            sig = ",".join(sig_parts) if sig_parts else "none"

            if sig not in cap_groups:
                cap_groups[sig] = []
            cap_groups[sig].append(device_id)

        for sig, device_ids in cap_groups.items():
            cluster = DeviceCluster(
                cluster_id=f"cap-{hash(sig) % 10000}",
                name=f"Capability: {sig[:30]}",
                strategy=strategy,
                device_ids=device_ids,
                attributes={"capability_signature": sig},
            )
            clusters.append(cluster)

    elif strategy == ClusterStrategy.LOCATION:
        location_groups = group_by_location(info_map)
        for location, device_ids in location_groups.items():
            cluster = DeviceCluster(
                cluster_id=f"loc-{location}",
                name=f"Location: {location}",
                strategy=strategy,
                device_ids=[d for d in device_ids if d in devices],
            )
            if not cluster.is_empty:
                clusters.append(cluster)

    elif strategy == ClusterStrategy.WEIGHTED:
        # Multi-factor clustering
        clusters = _weighted_cluster(devices, info_map, weights or {})

    else:
        # Default: single cluster with all devices
        clusters.append(DeviceCluster(
            cluster_id="all",
            name="All Devices",
            strategy=strategy,
            device_ids=devices,
        ))

    logger.info(
        "clustered %d devices into %d clusters using %s strategy",
        len(devices),
        len(clusters),
        strategy.value,
    )

    return clusters


def _weighted_cluster(
    devices: list[str],
    info_map: dict[str, dict[str, Any]],
    weights: dict[str, float],
) -> list[DeviceCluster]:
    """Perform weighted multi-factor clustering.

    Uses multiple attributes with weights to create clusters.
    """
    # Calculate composite scores for each device
    device_scores: dict[str, dict[str, float]] = {}

    for device_id in devices:
        info = info_map.get(device_id, {})
        scores: dict[str, float] = {}

        # Type score
        if weights.get("type", 0) > 0:
            device_type = info.get("device_type", "unknown")
            scores["type"] = hash(device_type) % 100 / 100.0

        # Location score
        if weights.get("location", 0) > 0:
            location = info.get("location", "unknown")
            scores["location"] = hash(location) % 100 / 100.0

        # Capability score
        if weights.get("capability", 0) > 0:
            caps = info.get("capabilities", {})
            scores["capability"] = len(caps) / 10.0  # Normalize

        device_scores[device_id] = scores

    # Simple clustering: group by dominant factor
    groups: dict[str, list[str]] = {}
    for device_id, scores in device_scores.items():
        if not scores:
            group_key = "default"
        else:
            # Find highest weighted score
            best = max(scores.items(), key=lambda x: x[1] * weights.get(x[0], 1.0))
            group_key = best[0]

        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(device_id)

    clusters = []
    for group_key, device_ids in groups.items():
        clusters.append(DeviceCluster(
            cluster_id=f"weighted-{group_key}",
            name=f"Group: {group_key}",
            strategy=ClusterStrategy.WEIGHTED,
            device_ids=device_ids,
            attributes={"weights": weights},
        ))

    return clusters


def find_cluster_for_device(
    clusters: list[DeviceCluster],
    device_id: str,
) -> DeviceCluster | None:
    """Find which cluster a device belongs to.

    Parameters
    ----------
    clusters : list[DeviceCluster]
        List of clusters to search.
    device_id : str
        The device to find.

    Returns
    -------
    DeviceCluster or None
        The cluster containing the device, or None if not found.
    """
    for cluster in clusters:
        if cluster.has_device(device_id):
            return cluster
    return None


def merge_clusters(
    clusters: list[DeviceCluster],
    cluster_ids: list[str],
    new_name: str = "merged",
) -> DeviceCluster | None:
    """Merge multiple clusters into one.

    Parameters
    ----------
    clusters : list[DeviceCluster]
        List of existing clusters.
    cluster_ids : list[str]
        IDs of clusters to merge.
    new_name : str
        Name for the new merged cluster.

    Returns
    -------
    DeviceCluster
        The new merged cluster, or None if no clusters found.
    """
    merged_devices: list[str] = []
    strategy = ClusterStrategy.CUSTOM

    for cluster in clusters:
        if cluster.cluster_id in cluster_ids:
            merged_devices.extend(cluster.device_ids)
            strategy = cluster.strategy

    if not merged_devices:
        return None

    # Remove duplicates while preserving order
    seen = set()
    unique_devices = []
    for d in merged_devices:
        if d not in seen:
            seen.add(d)
            unique_devices.append(d)

    return DeviceCluster(
        cluster_id=f"merged-{hash(str(cluster_ids)) % 10000}",
        name=new_name,
        strategy=strategy,
        device_ids=unique_devices,
    )