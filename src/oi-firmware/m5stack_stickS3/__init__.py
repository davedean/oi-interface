"""
M5Stack StickS3 Firmware for Oi v2.

This is the device-side firmware that runs on the M5Stack StickS3
and communicates with oi-gateway via DATP over WebSocket.

Components:
- DATP client and protocol handling
- Hardware drivers (display, audio, buttons, WiFi, power)
- UI rendering (status, cards)
- Main event loop

To use:
1. Copy secrets.py.example to a local secrets file outside the repo tree and configure WiFi/gateway
2. Flash to device using esptool or M5Burner
3. Device will connect to gateway and be ready for use

Device ID is auto-generated from MAC address if not configured.
"""

from .version import __version__, __device__, __firmware__, DEVICE_TYPE
from .boot import Firmware, init, get

__all__ = [
    # Version
    "__version__",
    "__device__",
    "__firmware__",
    "DEVICE_TYPE",
    # Boot
    "Firmware",
    "init",
    "get",
]
