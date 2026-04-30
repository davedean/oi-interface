"""
Hardware abstraction layer for M5Stack StickS3.

This module provides hardware drivers for:
- ST7789 display
- Button input
- ES8311 audio codec
- Power management
- WiFi connectivity
"""

from .display import ST7789Display, create_display, WIDTH, HEIGHT
from .buttons import Button, ButtonManager, create_button_manager
from .audio import AudioManager, create_audio_manager
from .power import PowerManager, create_power_manager
from .wifi import WiFiManager, create_wifi_manager

__all__ = [
    # Display
    "ST7789Display",
    "create_display",
    "WIDTH",
    "HEIGHT",
    # Buttons
    "Button",
    "ButtonManager",
    "create_button_manager",
    # Audio
    "AudioManager",
    "create_audio_manager",
    # Power
    "PowerManager",
    "create_power_manager",
    # WiFi
    "WiFiManager",
    "create_wifi_manager",
]