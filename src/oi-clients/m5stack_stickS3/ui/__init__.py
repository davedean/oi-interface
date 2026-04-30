"""
UI rendering for M5Stack StickS3.

This module provides UI components:
- Renderer - Display primitives
- StatusDisplay - Status indicator display
- CardDisplay - Message card display
"""

from .renderer import Renderer, create_renderer
from .status import StatusDisplay, create_status_display, STATUS_IDLE, STATUS_LISTENING, STATUS_THINKING, STATUS_RESPONSE_CACHED, STATUS_PLAYING, STATUS_MUTED, STATUS_OFFLINE, STATUS_ERROR, STATUS_CONFIRM
from .card import CardDisplay, ConfirmDialog, create_card_display

__all__ = [
    # Renderer
    "Renderer",
    "create_renderer",
    # Status display
    "StatusDisplay",
    "create_status_display",
    "STATUS_IDLE",
    "STATUS_LISTENING",
    "STATUS_THINKING",
    "STATUS_RESPONSE_CACHED",
    "STATUS_PLAYING",
    "STATUS_MUTED",
    "STATUS_OFFLINE",
    "STATUS_ERROR",
    "STATUS_CONFIRM",
    # Card display
    "CardDisplay",
    "ConfirmDialog",
    "create_card_display",
]