"""
DATP Protocol implementation for M5Stack StickS3 firmware.

This module provides the DATP client, message handling, state machine,
and event builders for device-to-gateway communication.
"""

from .client import DATPClient, create_client, STATE_DISCONNECTED, STATE_CONNECTING, STATE_HELLO_SENT, STATE_CONNECTED, STATE_RECONNECTING
from .state import DeviceState, State
from . import messages
from . import events

__all__ = [
    "DATPClient",
    "create_client",
    "DeviceState",
    "State",
    "messages",
    "events",
    # Connection states
    "STATE_DISCONNECTED",
    "STATE_CONNECTING",
    "STATE_HELLO_SENT",
    "STATE_CONNECTED",
    "STATE_RECONNECTING",
]