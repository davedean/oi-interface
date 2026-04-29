"""Multi-device management module.

This module handles:
- Multiple Stick devices with unique IDs
- Device grouping/clustering
- Load balancing across devices
- Device affinity and preference
"""
from .manager import (
    MultiDeviceManager,
    DeviceGroup,
    DeviceAffinity,
    LoadBalancer,
    get_multi_device_manager,
)
from .clustering import (
    DeviceCluster,
    ClusterStrategy,
    cluster_devices,
    group_by_capability,
    group_by_location,
    group_by_type,
)

__all__ = [
    "MultiDeviceManager",
    "DeviceGroup",
    "DeviceAffinity",
    "LoadBalancer",
    "get_multi_device_manager",
    "DeviceCluster",
    "ClusterStrategy",
    "cluster_devices",
    "group_by_capability",
    "group_by_location",
    "group_by_type",
]