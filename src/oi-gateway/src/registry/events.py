"""Registry-specific event type constants.

These are emitted as ``event_type`` strings on the shared :class:`datp.events.EventBus`.
"""

# A device has come online (connected and completed the hello handshake).
REGISTRY_DEVICE_ONLINE = "registry.device_online"

# A device has gone offline (WebSocket disconnected).
REGISTRY_DEVICE_OFFLINE = "registry.device_offline"

# A device has sent a state report (DATP type="state").
REGISTRY_STATE_UPDATED = "registry.state_updated"

# A device has been marked unhealthy (missed heartbeats).
REGISTRY_DEVICE_UNHEALTHY = "registry.device_unhealthy"

# A device has reconnected after a disconnection.
REGISTRY_DEVICE_RECONNECTED = "registry.device_reconnected"
