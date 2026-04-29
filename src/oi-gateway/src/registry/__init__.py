"""Device registry: tracks connected devices, capabilities, and state."""

from registry.models import DeviceInfo
from registry.events import (
    REGISTRY_DEVICE_ONLINE,
    REGISTRY_DEVICE_OFFLINE,
    REGISTRY_STATE_UPDATED,
    REGISTRY_DEVICE_UNHEALTHY,
    REGISTRY_DEVICE_RECONNECTED,
)
from registry.service import RegistryService
from registry.store import DeviceStore
from registry.reconnection import ReconnectionManager
from registry.heartbeat import HeartbeatMonitor

__all__ = [
    "DeviceInfo",
    "REGISTRY_DEVICE_ONLINE",
    "REGISTRY_DEVICE_OFFLINE",
    "REGISTRY_STATE_UPDATED",
    "REGISTRY_DEVICE_UNHEALTHY",
    "REGISTRY_DEVICE_RECONNECTED",
    "RegistryService",
    "DeviceStore",
    "ReconnectionManager",
    "HeartbeatMonitor",
]
