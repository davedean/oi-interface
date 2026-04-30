"""
ST7789 Display Driver for M5Stack StickS3.

This module provides the display driver for the 135x240 ST7789 display.
GPIO mapping:
- MOSI: G39
- SCK: G40
- RS/DC: G45
- CS: G41
- RST: G21
- BL: G38
"""

import machine
import ustruct
import utime


# Display dimensions
WIDTH = 135
HEIGHT = 240

# Color definitions (RGB565)
BLACK = 0x0000
WHITE = 0xFFFF
RED = 0xF800
GREEN = 0x07E0
BLUE = 0x001F
YELLOW = 0xFFE0
CYAN = 0x07FF
MAGENTA = 0xF81F
GRAY = 0x8410
DARK_GRAY = 0x4208
LIGHT_GRAY = 0xC618


# GPIO pins
PIN_MOSI = 39
PIN_SCK = 40
PIN_RS = 45
PIN_CS = 41
PIN_RST = 21
PIN_BL = 38


class ST7789Display:
    """
    ST7789 display driver for M5Stack StickS3.
    
    Provides methods to draw pixels, lines, rectangles, text, and more.
    """
    
    def __init__(self, spi=None):
        """
        Initialize the display.
        
        Args:
            spi: Optional SPI object. If None, creates one.
        """
        if spi is None:
            # Initialize SPI
            self.spi = machine.SPI(
                1,
                baudrate=8000000,
                polarity=0,
                phase=0,
                sck=machine.Pin(PIN_SCK),
                mosi=machine.Pin(PIN_MOSI)
            )
        else:
            self.spi = spi
        
        # Initialize GPIO pins
        self.cs = machine.Pin(PIN_CS, machine.Pin.OUT)
        self.rs = machine.Pin(PIN_RS, machine.Pin.OUT)
        self.rst = machine.Pin(PIN_RST, machine.Pin.OUT)
        self.bl = machine.Pin(PIN_BL, machine.Pin.OUT)
        
        # Initialize display
        self._init_display()
        
        # Current cursor position
        self._x = 0
        self._y = 0
        
        # Default colors
        self._fg_color = WHITE
        self._bg_color = BLACK
        
        # Font (simple 8x16 bitmap font)
        self._font = VGA2_8x16_FONT
    
    def _init_display(self):
        """Initialize the ST7789 display."""
        # Reset
        self.rst.value(0)
        utime.sleep_ms(10)
        self.rst.value(1)
        utime.sleep_ms(10)
        
        # Send initialization commands
        self._write_command(0x01)  # Software reset
        utime.sleep_ms(100)
        
        self._write_command(0x11)  # Sleep out
        utime.sleep_ms(100)
        
        self._write_command(0x3A)  # Color mode
        self._write_data(b'\x05')  # 16-bit RGB565
        
        self._write_command(0x36)  # Memory access control
        self._write_data(b'\x00')  # Normal orientation
        
        self._write_command(0x2A)  # Column address
        self._write_data(b'\x00\x00\x00\x87')  # 0-135
        
        self._write_command(0x2B)  # Row address
        self._write_data(b'\x00\x00\x00\xEF')  # 0-240
        
        self._write_command(0x21)  # Display inversion
        self._write_command(0x29)  # Display on
        
        # Turn on backlight
        self.bl.value(1)
    
    def _write_command(self, cmd: int):
        """Write a command to the display."""
        self.rs.value(0)
        self.cs.value(0)
        self.spi.write(bytes([cmd]))
        self.cs.value(1)
    
    def _write_data(self, data: bytes):
        """Write data to the display."""
        self.rs.value(1)
        self.cs.value(0)
        self.spi.write(data)
        self.cs.value(1)
    
    def _set_window(self, x: int, y: int, w: int, h: int):
        """Set the draw window."""
        x1 = x
        x2 = x + w - 1
        y1 = y
        y2 = y + h - 1
        
        self._write_command(0x2A)
        self._write_data(ustruct.pack('>HH', x1, x2))
        
        self._write_command(0x2B)
        self._write_data(ustruct.pack('>HH', y1, y2))
        
        self._write_command(0x2C)
    
    def clear(self, color: int = BLACK):
        """Clear the display with a color."""
        self.fill_rect(0, 0, WIDTH, HEIGHT, color)
    
    def fill_rect(self, x: int, y: int, w: int, h: int, color: int):
        """Fill a rectangle with a color."""
        if w <= 0 or h <= 0:
            return
        
        self._set_window(x, y, w, h)
        
        # Write pixel data
        self.rs.value(1)
        self.cs.value(0)
        
        # Create a buffer for the pixels
        # For efficiency, write in chunks
        chunk_size = 256
        pixel_data = ustruct.pack('<H', color)
        pixels = pixel_data * min(w, chunk_size)
        
        remaining = w * h
        while remaining > 0:
            write_len = min(chunk_size, remaining)
            self.spi.write(pixels[:write_len * 2])
            remaining -= write_len
        
        self.cs.value(1)
    
    def draw_pixel(self, x: int, y: int, color: int):
        """Draw a single pixel."""
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self._set_window(x, y, 1, 1)
            self.rs.value(1)
            self.cs.value(0)
            self.spi.write(ustruct.pack('<H', color))
            self.cs.value(1)
    
    def draw_line(self, x0: int, y0: int, x1: int, y1: int, color: int):
        """Draw a line using Bresenham's algorithm."""
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        
        while True:
            self.draw_pixel(x0, y0, color)
            
            if x0 == x1 and y0 == y1:
                break
            
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy
    
    def draw_rect(self, x: int, y: int, w: int, h: int, color: int):
        """Draw a rectangle outline."""
        self.draw_line(x, y, x + w - 1, y, color)
        self.draw_line(x, y + h - 1, x + w - 1, y + h - 1, color)
        self.draw_line(x, y, x, y + h - 1, color)
        self.draw_line(x + w - 1, y, x + w - 1, y + h - 1, color)
    
    def draw_circle(self, x0: int, y0: int, r: int, color: int):
        """Draw a circle outline."""
        x = r
        y = 0
        err = 0
        
        while x >= y:
            self.draw_pixel(x0 + x, y0 + y, color)
            self.draw_pixel(x0 + y, y0 + x, color)
            self.draw_pixel(x0 - y, y0 + x, color)
            self.draw_pixel(x0 - x, y0 + y, color)
            self.draw_pixel(x0 - x, y0 - y, color)
            self.draw_pixel(x0 - y, y0 - x, color)
            self.draw_pixel(x0 + y, y0 - x, color)
            self.draw_pixel(x0 + x, y0 - y, color)
            
            if err <= 0:
                y += 1
                err += 2 * y + 1
            if err > 0:
                x -= 1
                err -= 2 * x + 1
    
    def set_color(self, fg: int, bg: int = BLACK):
        """Set foreground and background colors."""
        self._fg_color = fg
        self._bg_color = bg
    
    def draw_text(self, x: int, y: int, text: str, bg: int = None):
        """Draw text using the 8x16 font."""
        if bg is None:
            bg = self._bg_color
        
        for char in text:
            char_ord = ord(char)
            if char_ord < 32 or char_ord > 126:
                char_ord = 32  # Space for unknown chars
            
            # Get font data (simplified - uses VGA2_8x16_FONT)
            font_data = self._font.get(char_ord, self._font.get(32))
            
            # Draw character (8x16 bitmap)
            for row in range(16):
                byte = font_data[row]
                for col in range(8):
                    if byte & (0x80 >> col):
                        self.draw_pixel(x + col, y + row, self._fg_color)
                    else:
                        self.draw_pixel(x + col, y + row, bg)
            
            x += 8
            
            # Wrap at edge of screen
            if x >= WIDTH - 8:
                x = 0
                y += 16
    
    def draw_icon(self, x: int, y: int, icon: bytes, w: int, h: int, 
                 fg: int = WHITE, bg: int = BLACK):
        """Draw an icon (monochrome bitmap)."""
        for row in range(h):
            byte = icon[row] if row < len(icon) else 0
            for col in range(min(w, 8)):
                if byte & (0x80 >> col):
                    self.draw_pixel(x + col, y + row, fg)
                else:
                    self.draw_pixel(x + col, y + row, bg)
    
    def set_brightness(self, value: int):
        """Set display brightness (0-255)."""
        # Map 0-255 to duty cycle
        # Use PWM on backlight pin if available
        # For simplicity, just on/off
        if value > 0:
            self.bl.value(1)
        else:
            self.bl.value(0)
    
    def sleep(self):
        """Put display to sleep."""
        self._write_command(0x10)
    
    def wake(self):
        """Wake display from sleep."""
        self._write_command(0x11)
        utime.sleep_ms(100)


# Simple 8x16 font (VGA style)
# Each character is 16 bytes (8x16 bitmap)
VGA2_8x16_FONT = {
    # Space
    32: bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
               0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
    # Exclamation
    33: bytes([0x18, 0x3C, 0x3C, 0x18, 0x18, 0x18, 0x00, 0x18,
               0x18, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
    # ... (other characters would be defined here)
}


def create_display(spi=None) -> ST7789Display:
    """Factory function to create a display instance."""
    return ST7789Display(spi)