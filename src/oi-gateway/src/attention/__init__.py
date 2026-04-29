"""Attention tracking and policy module.

This module handles tracking which device has user attention,
managing attention transitions, and implementing attention priority rules.

Attention is distinct from foreground:
- Foreground: the device most recently used for interaction (input)
- Attention: the device the user is currently focused on (can be different)
  e.g., user might be looking at dashboard (attention) while
  voice input comes from stick (foreground)
"""
from .policy import (
    AttentionPolicy,
    AttentionState,
    AttentionTransition,
    get_attention_policy,
)
from .events import (
    ATTENTION_CHANGED,
    ATTENTION_ACQUIRED,
    ATTENTION_RELEASED,
    ATTENTION_PRIORITY_UPDATED,
    ATTENTION_IDLE,
    ATTENTION_ACTIVE,
)

__all__ = [
    "AttentionPolicy",
    "AttentionState",
    "AttentionTransition",
    "get_attention_policy",
    "ATTENTION_CHANGED",
    "ATTENTION_ACQUIRED",
    "ATTENTION_RELEASED",
    "ATTENTION_PRIORITY_UPDATED",
    "ATTENTION_IDLE",
    "ATTENTION_ACTIVE",
]