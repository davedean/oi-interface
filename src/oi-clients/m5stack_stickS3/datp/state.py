"""
Device State Machine for M5Stack StickS3 firmware.

This module implements the device state machine as defined in the firmware plan.
"""

import utime


# Device states
class State:
    BOOTING = "BOOTING"
    PAIRING = "PAIRING"
    READY = "READY"
    RECORDING = "RECORDING"
    UPLOADING = "UPLOADING"
    THINKING = "THINKING"
    RESPONSE_CACHED = "RESPONSE_CACHED"
    PLAYING = "PLAYING"
    MUTED = "MUTED"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"
    SAFE_MODE = "SAFE_MODE"


# Valid state transitions
VALID_TRANSITIONS = {
    State.BOOTING: [State.PAIRING, State.READY, State.OFFLINE, State.ERROR],
    State.PAIRING: [State.READY, State.ERROR],
    State.READY: [State.RECORDING, State.MUTED, State.OFFLINE, State.BOOTING],
    State.RECORDING: [State.UPLOADING, State.READY],
    State.UPLOADING: [State.THINKING],
    State.THINKING: [State.RESPONSE_CACHED, State.READY, State.ERROR],
    State.RESPONSE_CACHED: [State.PLAYING, State.READY],
    State.PLAYING: [State.RESPONSE_CACHED, State.READY],
    State.MUTED: [State.READY, State.OFFLINE],
    State.OFFLINE: [State.READY, State.ERROR],
    State.ERROR: [State.SAFE_MODE, State.READY],
    State.SAFE_MODE: [State.BOOTING],
}


# Command handling by state
# execute = handle immediately
# queue = queue for later
# reject = reject with ACK ok=false
# ignore = ignore silently (no ACK)
COMMAND_HANDLING = {
    "display.show_status": {
        State.BOOTING: "queue",
        State.PAIRING: "queue",
        State.READY: "execute",
        State.RECORDING: "queue",
        State.UPLOADING: "queue",
        State.THINKING: "queue",
        State.RESPONSE_CACHED: "execute",
        State.PLAYING: "queue",
        State.MUTED: "execute",
        State.OFFLINE: "ignore",
        State.ERROR: "ignore",
        State.SAFE_MODE: "execute",
    },
    "display.show_card": {
        State.BOOTING: "queue",
        State.PAIRING: "queue",
        State.READY: "execute",
        State.RECORDING: "queue",
        State.UPLOADING: "queue",
        State.THINKING: "queue",
        State.RESPONSE_CACHED: "execute",
        State.PLAYING: "queue",
        State.MUTED: "execute",
        State.OFFLINE: "ignore",
        State.ERROR: "ignore",
        State.SAFE_MODE: "execute",
    },
    "audio.play": {
        State.BOOTING: "reject",
        State.PAIRING: "reject",
        State.READY: "execute",
        State.RECORDING: "reject",
        State.UPLOADING: "reject",
        State.THINKING: "queue",
        State.RESPONSE_CACHED: "execute",
        State.PLAYING: "queue",
        State.MUTED: "reject",
        State.OFFLINE: "reject",
        State.ERROR: "ignore",
        State.SAFE_MODE: "reject",
    },
    "audio.stop": {
        State.BOOTING: "reject",
        State.PAIRING: "reject",
        State.READY: "reject",
        State.RECORDING: "execute",
        State.UPLOADING: "queue",
        State.THINKING: "queue",
        State.RESPONSE_CACHED: "execute",
        State.PLAYING: "execute",
        State.MUTED: "reject",
        State.OFFLINE: "reject",
        State.ERROR: "ignore",
        State.SAFE_MODE: "reject",
    },
    "audio.cache.put_begin": {
        State.BOOTING: "queue",
        State.PAIRING: "queue",
        State.READY: "queue",
        State.RECORDING: "queue",
        State.UPLOADING: "queue",
        State.THINKING: "queue",
        State.RESPONSE_CACHED: "clear+execute",
        State.PLAYING: "queue",
        State.MUTED: "queue",
        State.OFFLINE: "ignore",
        State.ERROR: "ignore",
        State.SAFE_MODE: "ignore",
    },
    "audio.cache.put_chunk": {
        State.BOOTING: "reject",
        State.PAIRING: "reject",
        State.READY: "reject",
        State.RECORDING: "queue",
        State.UPLOADING: "execute",
        State.THINKING: "queue",
        State.RESPONSE_CACHED: "execute",
        State.PLAYING: "queue",
        State.MUTED: "queue",
        State.OFFLINE: "ignore",
        State.ERROR: "ignore",
        State.SAFE_MODE: "reject",
    },
    "device.set_volume": {
        State.BOOTING: "ignore",
        State.PAIRING: "ignore",
        State.READY: "execute",
        State.RECORDING: "ignore",
        State.UPLOADING: "ignore",
        State.THINKING: "ignore",
        State.RESPONSE_CACHED: "execute",
        State.PLAYING: "ignore",
        State.MUTED: "execute",
        State.OFFLINE: "ignore",
        State.ERROR: "ignore",
        State.SAFE_MODE: "ignore",
    },
    "device.set_brightness": {
        State.BOOTING: "ignore",
        State.PAIRING: "ignore",
        State.READY: "execute",
        State.RECORDING: "ignore",
        State.UPLOADING: "ignore",
        State.THINKING: "ignore",
        State.RESPONSE_CACHED: "execute",
        State.PLAYING: "ignore",
        State.MUTED: "execute",
        State.OFFLINE: "ignore",
        State.ERROR: "ignore",
        State.SAFE_MODE: "ignore",
    },
    "device.mute_until": {
        State.BOOTING: "ignore",
        State.PAIRING: "ignore",
        State.READY: "execute",
        State.RECORDING: "ignore",
        State.UPLOADING: "ignore",
        State.THINKING: "ignore",
        State.RESPONSE_CACHED: "execute",
        State.PLAYING: "ignore",
        State.MUTED: "execute",
        State.OFFLINE: "ignore",
        State.ERROR: "ignore",
        State.SAFE_MODE: "ignore",
    },
    "device.reboot": {
        State.BOOTING: "ignore",
        State.PAIRING: "execute",
        State.READY: "execute",
        State.RECORDING: "execute",
        State.UPLOADING: "execute",
        State.THINKING: "execute",
        State.RESPONSE_CACHED: "execute",
        State.PLAYING: "execute",
        State.MUTED: "execute",
        State.OFFLINE: "execute",
        State.ERROR: "execute",
        State.SAFE_MODE: "execute",
    },
    "device.shutdown": {
        State.BOOTING: "ignore",
        State.PAIRING: "execute",
        State.READY: "execute",
        State.RECORDING: "execute",
        State.UPLOADING: "execute",
        State.THINKING: "execute",
        State.RESPONSE_CACHED: "execute",
        State.PLAYING: "execute",
        State.MUTED: "execute",
        State.OFFLINE: "ignore",
        State.ERROR: "ignore",
        State.SAFE_MODE: "ignore",
    },
    "wifi.configure": {
        State.BOOTING: "ignore",
        State.PAIRING: "execute",
        State.READY: "execute",
        State.RECORDING: "ignore",
        State.UPLOADING: "ignore",
        State.THINKING: "ignore",
        State.RESPONSE_CACHED: "execute",
        State.PLAYING: "ignore",
        State.MUTED: "execute",
        State.OFFLINE: "ignore",
        State.ERROR: "ignore",
        State.SAFE_MODE: "ignore",
    },
    "storage.format": {
        State.BOOTING: "ignore",
        State.PAIRING: "ignore",
        State.READY: "execute",
        State.RECORDING: "ignore",
        State.UPLOADING: "ignore",
        State.THINKING: "ignore",
        State.RESPONSE_CACHED: "execute",
        State.PLAYING: "ignore",
        State.MUTED: "execute",
        State.OFFLINE: "ignore",
        State.ERROR: "ignore",
        State.SAFE_MODE: "ignore",
    },
}


class DeviceState:
    """
    Device state machine implementation.
    
    Manages state transitions, command handling, and device metrics.
    """
    
    def __init__(self):
        self._mode = State.BOOTING
        self._boot_time = utime.time()
        self._state_start_time = utime.time()
        
        # Device metrics
        self._battery_percent = 100
        self._charging = False
        self._wifi_rssi = -100
        self._audio_cache_used_bytes = 0
        self._muted_until = None
        
        # Queued commands (for states that queue)
        self._command_queue = []
        self._max_queue_size = 5
        
        # Current stream ID for recording
        self._current_stream_id = None
        self._recording_start_time = None
    
    def get_mode(self) -> str:
        """Get current device mode."""
        return self._mode
    
    def set_mode(self, mode: str):
        """Set device mode (with transition validation)."""
        if mode == self._mode:
            return
        
        valid_targets = VALID_TRANSITIONS.get(self._mode, [])
        if mode not in valid_targets:
            print("Invalid transition: {} -> {}".format(self._mode, mode))
            return
        
        print("State transition: {} -> {}".format(self._mode, mode))
        old_mode = self._mode
        self._mode = mode
        self._state_start_time = utime.time()
        
        # Handle mode-specific initialization
        if mode == State.RECORDING:
            self._start_recording()
        elif mode == State.READY and old_mode == State.RECORDING:
            self._stop_recording()
        elif mode == State.OFFLINE:
            self._handle_offline()
        elif mode == State.ERROR:
            self._handle_error()
    
    def get_state(self) -> dict:
        """Get full state dict for hello and state reports."""
        return {
            "mode": self._mode,
            "battery_percent": self._battery_percent,
            "charging": self._charging,
            "wifi_rssi": self._wifi_rssi,
            "heap_free": 0,  # Will be filled by caller
            "uptime_s": utime.time() - self._boot_time,
            "audio_cache_used_bytes": self._audio_cache_used_bytes,
            "muted_until": self._muted_until,
        }
    
    def can_handle_command(self, op: str) -> bool:
        """Check if a command can be handled in current state."""
        handling = COMMAND_HANDLING.get(op, {})
        return handling.get(self._mode) in ("execute", "clear+execute")
    
    def get_command_handling(self, op: str) -> str:
        """Get how a command should be handled in current state."""
        handling = COMMAND_HANDLING.get(op, {})
        return handling.get(self._mode, "ignore")
    
    def queue_command(self, command: dict) -> bool:
        """Queue a command for later execution."""
        if len(self._command_queue) >= self._max_queue_size:
            return False
        self._command_queue.append(command)
        return True
    
    def get_queued_commands(self) -> list:
        """Get and clear queued commands."""
        commands = self._command_queue
        self._command_queue = []
        return commands
    
    def set_battery(self, percent: int, charging: bool = False):
        """Set battery state."""
        self._battery_percent = max(0, min(100, percent))
        self._charging = charging
    
    def set_wifi_rssi(self, rssi: int):
        """Set WiFi signal strength."""
        self._wifi_rssi = rssi
    
    def set_audio_cache_size(self, bytes_used: int):
        """Set audio cache size."""
        self._audio_cache_used_bytes = bytes_used
    
    def set_muted_until(self, timestamp: str):
        """Set mute expiration time."""
        self._muted_until = timestamp
        if timestamp:
            # Check if we should enter muted state
            # For now, just store the timestamp
            pass
    
    def check_mute_expiration(self):
        """Check if mute has expired."""
        if self._muted_until:
            # Compare with current time
            # For simplicity, assume if we're in MUTED state, check expiration
            pass
    
    # Recording management
    def _start_recording(self):
        """Start audio recording."""
        import uhashlib
        import uos
        # Generate stream ID
        data = "{}{}".format(self._mode, utime.time())
        h = uhashlib.sha256()
        h.update(data.encode())
        self._current_stream_id = "rec_" + h.hexdigest()[:8]
        self._recording_start_time = utime.ticks_ms()
    
    def _stop_recording(self):
        """Stop audio recording."""
        self._current_stream_id = None
        self._recording_start_time = None
    
    def get_current_stream_id(self) -> str:
        """Get current recording stream ID."""
        return self._current_stream_id
    
    def get_recording_duration_ms(self) -> int:
        """Get current recording duration in milliseconds."""
        if self._recording_start_time:
            return utime.ticks_diff(utime.ticks_ms(), self._recording_start_time)
        return 0
    
    # State-specific handlers
    def _handle_offline(self):
        """Handle entering offline state."""
        # Clear recording if in progress
        if self._current_stream_id:
            self._stop_recording()
    
    def _handle_error(self):
        """Handle entering error state."""
        # Clear any pending operations
        if self._current_stream_id:
            self._stop_recording()
        self._command_queue = []
    
    # State queries
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._mode == State.RECORDING
    
    def is_playing(self) -> bool:
        """Check if currently playing audio."""
        return self._mode == State.PLAYING
    
    def is_online(self) -> bool:
        """Check if device is online (connected to gateway)."""
        return self._mode not in (State.OFFLINE, State.ERROR, State.SAFE_MODE)
    
    def is_muted(self) -> bool:
        """Check if device is muted."""
        return self._mode == State.MUTED
    
    def can_record(self) -> bool:
        """Check if device can start recording."""
        return self._mode in (State.READY, State.MUTED)
    
    def can_play(self) -> bool:
        """Check if device can play audio."""
        return self._mode in (State.READY, State.RESPONSE_CACHED)