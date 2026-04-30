"""
Event builders for DATP protocol.

This module provides convenient functions to build various device events
that are sent to the gateway.
"""

from . import messages


def button_pressed(device_id: str, button: str = "main") -> str:
    """Build a button pressed event."""
    return messages.build_event(device_id, "button.pressed", button=button)


def button_released(device_id: str, button: str = "main") -> str:
    """Build a button released event."""
    return messages.build_event(device_id, "button.released", button=button)


def button_long_hold_started(device_id: str, button: str = "main") -> str:
    """Build a button long hold started event."""
    return messages.build_event(device_id, "button.long_hold_started", button=button)


def button_long_hold_ended(device_id: str, button: str = "main", 
                          hold_duration_ms: int = 0) -> str:
    """Build a button long hold ended event."""
    return messages.build_event(
        device_id, "button.long_hold_ended", 
        button=button,
        hold_duration_ms=hold_duration_ms
    )


def device_state_changed(device_id: str, old_state: str, new_state: str) -> str:
    """Build a device state changed event."""
    return messages.build_event(
        device_id, "device.state_changed",
        old_state=old_state,
        new_state=new_state
    )


def device_boot_completed(device_id: str, firmware: str) -> str:
    """Build a device boot completed event."""
    return messages.build_event(
        device_id, "device.boot_completed",
        firmware=firmware
    )


def device_wifi_connected(device_id: str, ssid: str, rssi: int) -> str:
    """Build a WiFi connected event."""
    return messages.build_event(
        device_id, "device.wifi_connected",
        ssid=ssid,
        rssi=rssi
    )


def device_wifi_disconnected(device_id: str, reason: str = "unknown") -> str:
    """Build a WiFi disconnected event."""
    return messages.build_event(
        device_id, "device.wifi_disconnected",
        reason=reason
    )


def device_battery_low(device_id: str, percent: int) -> str:
    """Build a battery low warning event."""
    return messages.build_event(
        device_id, "device.battery_low",
        percent=percent
    )


def device_battery_critical(device_id: str, percent: int) -> str:
    """Build a battery critical warning event."""
    return messages.build_event(
        device_id, "device.battery_critical",
        percent=percent
    )


def device_charging_started(device_id: str) -> str:
    """Build a charging started event."""
    return messages.build_event(device_id, "device.charging_started")


def device_charging_stopped(device_id: str, percent: int) -> str:
    """Build a charging stopped event."""
    return messages.build_event(
        device_id, "device.charging_stopped",
        percent=percent
    )


def audio_recording_started(device_id: str, stream_id: str) -> str:
    """Build an audio recording started event."""
    return messages.build_event(
        device_id, "audio.recording_started",
        stream_id=stream_id
    )


def audio_recording_finished(device_id: str, stream_id: str, 
                            duration_ms: int, original_sample_rate: int = 44100,
                            original_channels: int = 2) -> str:
    """Build an audio recording finished event."""
    return messages.build_audio_recording_finished(
        device_id, stream_id, duration_ms,
        original_sample_rate, original_channels
    )


def audio_playback_started(device_id: str, response_id: str) -> str:
    """Build an audio playback started event."""
    return messages.build_event(
        device_id, "audio.playback_started",
        response_id=response_id
    )


def audio_playback_finished(device_id: str, response_id: str) -> str:
    """Build an audio playback finished event."""
    return messages.build_event(
        device_id, "audio.playback_finished",
        response_id=response_id
    )


def audio_playback_error(device_id: str, response_id: str, error: str) -> str:
    """Build an audio playback error event."""
    return messages.build_event(
        device_id, "audio.playback_error",
        response_id=response_id,
        error=error
    )


def display_button_pressed(device_id: str, button_id: str) -> str:
    """Build a display button pressed event (from UI interaction)."""
    return messages.build_event(
        device_id, "display.button_pressed",
        button_id=button_id
    )


def error_event(device_id: str, code: str, message: str, related_id: str = None) -> str:
    """Build a device error event."""
    return messages.build_error(device_id, code, message, related_id)


class EventBuilder:
    """
    Event builder for creating multiple related events.
    
    Usage:
        builder = EventBuilder(device_id)
        builder.button_pressed("main")
        builder.button_long_hold_started("main")
        # Get all events as list
        events = builder.get_events()
    """
    
    def __init__(self, device_id: str):
        self.device_id = device_id
        self._events = []
    
    def add_event(self, event_json: str):
        """Add an event to the builder."""
        self._events.append(event_json)
    
    def button_pressed(self, button: str = "main"):
        """Add a button pressed event."""
        self.add_event(button_pressed(self.device_id, button))
    
    def button_released(self, button: str = "main"):
        """Add a button released event."""
        self.add_event(button_released(self.device_id, button))
    
    def button_long_hold_started(self, button: str = "main"):
        """Add a button long hold started event."""
        self.add_event(button_long_hold_started(self.device_id, button))
    
    def button_long_hold_ended(self, button: str = "main", hold_duration_ms: int = 0):
        """Add a button long hold ended event."""
        self.add_event(button_long_hold_ended(self.device_id, button, hold_duration_ms))
    
    def device_state_changed(self, old_state: str, new_state: str):
        """Add a device state changed event."""
        self.add_event(device_state_changed(self.device_id, old_state, new_state))
    
    def audio_recording_finished(self, stream_id: str, duration_ms: int,
                                original_sample_rate: int = 44100,
                                original_channels: int = 2):
        """Add an audio recording finished event."""
        self.add_event(audio_recording_finished(
            self.device_id, stream_id, duration_ms,
            original_sample_rate, original_channels
        ))
    
    def get_events(self) -> list:
        """Get all events as list of JSON strings."""
        return self._events
    
    def clear(self):
        """Clear all events."""
        self._events = []