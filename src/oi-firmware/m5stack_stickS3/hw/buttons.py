"""
Button Input Handling for M5Stack StickS3.

This module handles button input for:
- G11 (BtnA) - main/primary button
- G12 (BtnB) - secondary button

Features:
- Short press detection
- Long hold detection with configurable threshold
- Button state callbacks
"""

import machine
import utime


# GPIO pins
PIN_BTN_A = 11  # Main button
PIN_BTN_B = 12  # Secondary button

# Button pin configuration
BTN_PULL = machine.Pin.PULL_UP
BTN_ACTIVE = 0  # Active low (pressed = 0)

# Default thresholds
DEFAULT_LONG_HOLD_MS = 1000  # 1 second for long hold


class Button:
    """
    Single button handler with press and long-hold detection.
    """
    
    def __init__(self, pin: int, name: str = "btn",
                 long_hold_ms: int = DEFAULT_LONG_HOLD_MS):
        """
        Initialize button handler.
        
        Args:
            pin: GPIO pin number
            name: Button name for identification
            long_hold_ms: Duration in ms to trigger long hold
        """
        self.pin_num = pin
        self.name = name
        self.long_hold_ms = long_hold_ms
        
        # Initialize pin
        self._pin = machine.Pin(pin, machine.Pin.IN, BTN_PULL)
        
        # State
        self._pressed = False
        self._press_start = None
        self._long_hold_fired = False
        
        # Callbacks
        self._on_pressed = None
        self._on_released = None
        self._on_long_hold_start = None
        self._on_long_hold_end = None
    
    def set_callbacks(self, on_pressed=None, on_released=None,
                     on_long_hold_start=None, on_long_hold_end=None):
        """Set button event callbacks."""
        self._on_pressed = on_pressed
        self._on_released = on_released
        self._on_long_hold_start = on_long_hold_start
        self._on_long_hold_end = on_long_hold_end
    
    def is_pressed(self) -> bool:
        """Check if button is currently pressed."""
        return self._pin.value() == BTN_ACTIVE
    
    def update(self):
        """Update button state. Call this in main loop."""
        currently_pressed = self.is_pressed()
        
        if currently_pressed and not self._pressed:
            # Button just pressed
            self._pressed = True
            self._press_start = utime.ticks_ms()
            self._long_hold_fired = False
            
            if self._on_pressed:
                self._on_pressed(self.name)
        
        elif currently_pressed and self._pressed:
            # Button is being held - check for long hold
            if not self._long_hold_fired:
                hold_time = utime.ticks_diff(utime.ticks_ms(), self._press_start)
                if hold_time >= self.long_hold_ms:
                    self._long_hold_fired = True
                    if self._on_long_hold_start:
                        self._on_long_hold_start(self.name, hold_time)
        
        elif not currently_pressed and self._pressed:
            # Button just released
            was_long_held = self._long_hold_fired
            
            if self._long_hold_fired and self._on_long_hold_end:
                hold_duration = utime.ticks_diff(utime.ticks_ms(), self._press_start)
                self._on_long_hold_end(self.name, hold_duration)
            
            if self._on_released and not self._long_hold_fired:
                self._on_released(self.name)
            
            # Reset state
            self._pressed = False
            self._press_start = None
            self._long_hold_fired = False
    
    def get_hold_duration_ms(self) -> int:
        """Get current hold duration in milliseconds."""
        if self._pressed and self._press_start:
            return utime.ticks_diff(utime.ticks_ms(), self._press_start)
        return 0


class ButtonManager:
    """
    Manages multiple buttons and provides a unified interface.
    """
    
    def __init__(self, long_hold_ms: int = DEFAULT_LONG_HOLD_MS):
        """
        Initialize button manager.
        
        Args:
            long_hold_ms: Default long hold duration for all buttons
        """
        self.long_hold_ms = long_hold_ms
        
        # Create buttons
        self.buttons = {
            "main": Button(PIN_BTN_A, "main", long_hold_ms),
            "a": Button(PIN_BTN_A, "a", long_hold_ms),  # Alias for main
            "b": Button(PIN_BTN_B, "b", long_hold_ms),
        }
        
        # Event aggregator
        self._on_any_pressed = None
        self._on_any_released = None
        self._on_any_long_hold_start = None
        self._on_any_long_hold_end = None
    
    def set_global_callbacks(self, on_any_pressed=None, on_any_released=None,
                            on_any_long_hold_start=None, on_any_long_hold_end=None):
        """Set callbacks that fire for any button."""
        self._on_any_pressed = on_any_pressed
        self._on_any_released = on_any_released
        self._on_any_long_hold_start = on_any_long_hold_start
        self._on_any_long_hold_end = on_any_long_hold_end
        
        # Wire up individual buttons
        for btn in self.buttons.values():
            btn.set_callbacks(
                on_pressed=self._wrap_callback(on_any_pressed),
                on_released=self._wrap_callback(on_any_released),
                on_long_hold_start=on_any_long_hold_start,
                on_long_hold_end=on_any_long_hold_end,
            )
    
    def _wrap_callback(self, callback):
        """Wrap callback to add button name."""
        if callback:
            def wrapped(name, *args, **kwargs):
                callback(name, *args, **kwargs)
            return wrapped
        return None
    
    def update(self):
        """Update all buttons. Call in main loop."""
        for btn in self.buttons.values():
            btn.update()
    
    def is_any_pressed(self) -> bool:
        """Check if any button is currently pressed."""
        return any(btn.is_pressed() for btn in self.buttons.values())
    
    def get_pressed_buttons(self) -> list:
        """Get list of currently pressed button names."""
        return [name for name, btn in self.buttons.items() if btn.is_pressed()]
    
    def get_button(self, name: str) -> Button:
        """Get a specific button by name."""
        return self.buttons.get(name)


def create_button_manager(long_hold_ms: int = DEFAULT_LONG_HOLD_MS) -> ButtonManager:
    """Factory function to create a button manager."""
    return ButtonManager(long_hold_ms)


# Simple event-driven usage example:
#
# def on_button_pressed(name):
#     print("Button pressed:", name)
#
# def on_button_released(name):
#     print("Button released:", name)
#
# def on_long_hold_start(name, duration_ms):
#     print("Long hold started:", name, duration_ms)
#
# def on_long_hold_end(name, duration_ms):
#     print("Long hold ended:", name, duration_ms)
#
# manager = create_button_manager()
# manager.set_global_callbacks(
#     on_any_pressed=on_button_pressed,
#     on_any_released=on_button_released,
#     on_any_long_hold_start=on_long_hold_start,
#     on_any_long_hold_end=on_long_hold_end,
# )
#
# while True:
#     manager.update()
#     utime.sleep_ms(10)