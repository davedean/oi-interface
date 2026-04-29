"""
Display renderer primitives for M5Stack StickS3.

This module provides low-level drawing functions for the display.
"""

from .display import WHITE, BLACK, RED, GREEN, BLUE, YELLOW, CYAN, MAGENTA, GRAY


class Renderer:
    """
    Display renderer providing drawing primitives.
    
    Provides methods for drawing shapes, text, and icons on the ST7789 display.
    """
    
    def __init__(self, display):
        """
        Initialize renderer with a display.
        
        Args:
            display: ST7789Display instance
        """
        self._display = display
        self._width = display.WIDTH
        self._height = display.HEIGHT
        
        # Default colors
        self._fg = WHITE
        self._bg = BLACK
    
    def set_color(self, fg: int, bg: int = BLACK):
        """Set foreground and background colors."""
        self._fg = fg
        self._bg = bg
    
    def clear(self, color: int = None):
        """Clear the display."""
        self._display.clear(color if color is not None else self._bg)
    
    def pixel(self, x: int, y: int, color: int = None):
        """Draw a pixel."""
        self._display.draw_pixel(x, y, color if color is not None else self._fg)
    
    def line(self, x0: int, y0: int, x1: int, y1: int, color: int = None):
        """Draw a line."""
        self._display.draw_line(x0, y0, x1, y1, color if color is not None else self._fg)
    
    def rect(self, x: int, y: int, w: int, h: int, 
             color: int = None, fill: bool = False):
        """Draw a rectangle."""
        if fill:
            self._display.fill_rect(x, y, w, h, color if color is not None else self._fg)
        else:
            self._display.draw_rect(x, y, w, h, color if color is not None else self._fg)
    
    def circle(self, x: int, y: int, r: int, color: int = None, fill: bool = False):
        """Draw a circle."""
        if fill:
            # Simple fill - scanline
            for dy in range(-r, r + 1):
                dx = int((r * r - dy * dy) ** 0.5)
                self.line(x - dx, y + dy, x + dx, y + dy, color)
        else:
            self._display.draw_circle(x, y, r, color if color is not None else self._fg)
    
    def text(self, x: int, y: int, text: str, color: int = None, bg: int = None):
        """Draw text."""
        self._display.set_color(color if color is not None else self._bg, 
                               bg if bg is not None else self._bg)
        self._display.draw_text(x, y, text, bg)
    
    def text_centered(self, y: int, text: str, color: int = None, bg: int = None):
        """Draw text centered horizontally."""
        # Estimate width (8 pixels per character)
        text_width = len(text) * 8
        x = (self._width - text_width) // 2
        self.text(x, y, text, color, bg)
    
    def icon(self, x: int, y: int, icon_data: bytes, w: int, h: int,
             color: int = None, bg: int = None):
        """Draw an icon (monochrome bitmap)."""
        self._display.draw_icon(x, y, icon_data, w, h,
                                color if color is not None else self._fg,
                                bg if bg is not None else self._bg)
    
    def loading(self, x: int, y: int, progress: float, 
                width: int = 50, height: int = 6):
        """Draw a loading bar."""
        filled = int((width - 2) * min(1.0, max(0.0, progress)))
        
        # Background
        self.rect(x, y, width, height, GRAY, fill=True)
        
        # Filled portion
        if filled > 0:
            self.rect(x + 1, y + 1, filled, height - 2, self._fg, fill=True)
    
    def spinner(self, x: int, y: int, frame: int, radius: int = 10):
        """Draw an animated spinner."""
        import math
        
        # Draw 8 segments, rotate based on frame
        for i in range(8):
            angle = (frame + i) * (2 * math.pi / 8)
            x1 = int(x + radius * math.cos(angle))
            y1 = int(y + radius * math.sin(angle))
            x2 = int(x + (radius - 3) * math.cos(angle))
            y2 = int(y + (radius - 3) * math.sin(angle))
            self.line(x1, y1, x2, y2, self._fg)
    
    def progress_circle(self, x: int, y: int, progress: float, radius: int = 15):
        """Draw a circular progress indicator."""
        import math
        
        # Draw arc
        end_angle = 2 * math.pi * min(1.0, max(0.0, progress))
        
        # Draw arc segments
        segments = 36
        for i in range(segments):
            if i / segments <= progress:
                angle = (i / segments) * 2 * math.pi - math.pi / 2
                x1 = int(x + radius * math.cos(angle))
                y1 = int(y + radius * math.sin(angle))
                x2 = int(x + (radius - 3) * math.cos(angle))
                y2 = int(y + (radius - 3) * math.sin(angle))
                self.line(x1, y1, x2, y2, self._fg)


def create_renderer(display) -> Renderer:
    """Factory function to create a renderer."""
    return Renderer(display)