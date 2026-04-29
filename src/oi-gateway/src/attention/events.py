"""Attention-related events for the internal event bus."""

# Event types
ATTENTION_CHANGED = "attention.changed"
ATTENTION_ACQUIRED = "attention.acquired"  # User focused on a device
ATTENTION_RELEASED = "attention.released"  # User stopped focusing on a device
ATTENTION_PRIORITY_UPDATED = "attention.priority_updated"

# Attention states
ATTENTION_IDLE = "idle"
ATTENTION_ACTIVE = "active"