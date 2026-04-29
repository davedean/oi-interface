"""
Status display for M5Stack StickS3.

This module provides status display functionality showing the device state
(idle, listening, thinking, response_cached, playing, muted, offline, error).
"""

import utime


# Status states
STATUS_IDLE = "idle"
STATUS_LISTENING = "listening"
STATUS_THINKING = "thinking"
STATUS_RESPONSE_CACHED = "response_cached"
STATUS_PLAYING = "playing"
STATUS_MUTED = "muted"
STATUS_OFFLINE = "offline"
STATUS_ERROR = "error"
STATUS_CONFIRM = "confirm"


# Status colors
STATUS_COLORS = {
    STATUS_IDLE: 0x8410,          # Gray
    STATUS_LISTENING: 0x07E0,     # Green
    STATUS_THINKING: 0xF800,      # Red
    STATUS_RESPONSE_CACHED: 0x001F, # Blue
    STATUS_PLAYING: 0x07E0,       # Green
    STATUS_MUTED: 0xF800,         # Red
    STATUS_OFFLINE: 0x8410,       # Gray
    STATUS_ERROR: 0xF800,         # Red
    STATUS_CONFIRM: 0xFFE0,       # Yellow
}


class StatusDisplay:
    """
    Status display showing device state on the screen.
    
    Displays status icons and labels for the current device state.
    """
    
    def __init__(self, renderer, width: int = 135, height: int = 240):
        """
        Initialize status display.
        
        Args:
            renderer: Renderer instance
            width: Display width
            height: Display height
        """
        self._renderer = renderer
        self._width = width
        self._height = height
        
        # Current status
        self._status = STATUS_IDLE
        self._label = ""
        
        # Animation state
        self._animation_frame = 0
        self._animation_last_update = 0
        self._animation_interval = 100  # ms between frames
        
        # Icon data (simple bitmaps - would be loaded from file in real implementation)
        self._icons = self._load_icons()
    
    def _load_icons(self) -> dict:
        """Load icon bitmap data."""
        # Simple placeholder icons (8x8 or 16x16 bitmaps)
        return {
            STATUS_IDLE: self._make_circle_icon(8),
            STATUS_LISTENING: self._make_mic_icon(12),
            STATUS_THINKING: self._make_dots_icon(12),
            STATUS_RESPONSE_CACHED: self._make_download_icon(12),
            STATUS_PLAYING: self._make_play_icon(12),
            STATUS_MUTED: self._make_mute_icon(12),
            STATUS_OFFLINE: self._make_wifi_off_icon(12),
            STATUS_ERROR: self._make_x_icon(12),
            STATUS_CONFIRM: self._make_question_icon(12),
        }
    
    def _make_circle_icon(self, size: int) -> bytes:
        """Make a circle icon."""
        data = bytearray(size)
        # Simple filled circle pattern
        for i in range(size):
            data[i] = 0xFF  # Simplified
        return bytes(data)
    
    def _make_mic_icon(self, size: int) -> bytes:
        """Make a microphone icon."""
        return b'\x18\x3C\x7E\xFF\xFF\x7E\x3C\x18' + b'\x00\x18\x18\x18\x18\x00'
    
    def _make_dots_icon(self, size: int) -> bytes:
        """Make a dots (thinking) icon."""
        return b'\x00\x18\x00\x18\x00\x18\x00\x00' * 2
    
    def _make_download_icon(self, size: int) -> bytes:
        """Make a download (cached) icon."""
        return b'\x7E\x81\x81\x81\x81\x7E\x00\x18\x18\x18\x18\x18'
    
    def _make_play_icon(self, size: int) -> bytes:
        """Make a play icon."""
        return b'\x08\x1C\x3E\x7F\x3E\x1C\x08\x00'
    
    def _make_mute_icon(self, size: int) -> bytes:
        """Make a mute icon."""
        return b'\x7E\x81\x99\xBD\x81\x7E\x00\x00'
    
    def _make_wifi_off_icon(self, size: int) -> bytes:
        """Make a WiFi off icon."""
        return b'\x1C\x22\x41\x82\x41\x22\x1C\x00'
    
    def _make_x_icon(self, size: int) -> bytes:
        """Make an X (error) icon."""
        return b'\x81\x42\x24\x18\x24\x42\x81\x00'
    
    def _make_question_icon(self, size: int) -> bytes:
        """Make a question mark icon."""
        return b'\x3C\x66\xC3\x81\x81\x81\x66\x3C'
    
    def show_status(self, status: str, label: str = ""):
        """
        Show a status on the display.
        
        Args:
            status: Status type (idle, listening, etc.)
            label: Optional label text
        """
        self._status = status
        self._label = label
        self._render()
    
    def _render(self):
        """Render the current status."""
        # Clear screen
        self._renderer.clear()
        
        # Get colors
        fg_color = STATUS_COLORS.get(self._status, 0xFFFF)
        
        # Draw icon
        icon = self._icons.get(self._status)
        if icon:
            # Center in upper portion of screen
            icon_x = (self._width - 16) // 2
            icon_y = 60
            self._renderer.icon(icon_x, icon_y, icon, 16, 16, fg_color)
        
        # Draw status text
        status_text = self._status.upper()
        self._renderer.text_centered(90, status_text, fg_color)
        
        # Draw label if provided
        if self._label:
            label_y = 120
            # Truncate if too long
            if len(self._label) > 16:
                label = self._label[:14] + ".."
            else:
                label = self._label
            self._renderer.text_centered(label_y, label, 0xFFFF)
        
        # Draw status-specific indicators
        self._draw_status_indicator(fg_color)
    
    def _draw_status_indicator(self, color: int):
        """Draw status-specific visual indicator."""
        if self._status == STATUS_THINKING:
            # Animate spinner
            cx = self._width // 2
            cy = 60
            self._renderer.spinner(cx, cy, self._animation_frame)
        
        elif self._status == STATUS_PLAYING:
            # Draw progress indicator
            cx = self._width // 2
            cy = 60
            self._renderer.progress_circle(cx, cy, self._animation_frame / 20)
    
    def update(self):
        """Update animation. Call this in main loop."""
        now = utime.ticks_ms()
        
        if utime.ticks_diff(now, self._animation_last_update) > self._animation_interval:
            self._animation_frame = (self._animation_frame + 1) % 20
            self._animation_last_update = now
            
            # Re-render for animated states
            if self._status in (STATUS_THINKING, STATUS_PLAYING):
                self._render()
    
    def get_status(self) -> str:
        """Get current status."""
        return self._status
    
    def get_label(self) -> str:
        """Get current label."""
        return self._label


def create_status_display(renderer, width: int = 135, height: int = 240) -> StatusDisplay:
    """Factory function to create a status display."""
    return StatusDisplay(renderer, width, height)