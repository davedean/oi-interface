"""
Boot initialization for M5Stack StickS3 firmware.

This module initializes hardware on boot:
- Display initialization
- Button initialization
- Audio initialization
- WiFi initialization
- Power initialization
"""

import machine
import gc
import utime


# Import hardware modules
from hw import (
    create_display,
    create_button_manager,
    create_audio_manager,
    create_power_manager,
    create_wifi_manager,
)


# Import UI modules
from ui import (
    create_renderer,
    create_status_display,
    create_card_display,
)


# Import DATP
from datp import DATPClient, DeviceState


class Firmware:
    """
    Firmware instance managing all components.
    """
    
    def __init__(self):
        """Initialize firmware components."""
        # Display
        print("Initializing display...")
        self.display = create_display()
        self.renderer = create_renderer(self.display)
        
        # Status and card display
        print("Initializing UI...")
        self.status_display = create_status_display(self.renderer)
        self.card_display = create_card_display(self.renderer)
        
        # Buttons
        print("Initializing buttons...")
        self.buttons = create_button_manager()
        self.buttons.set_global_callbacks(
            on_any_pressed=self._on_button_pressed,
            on_any_released=self._on_button_released,
            on_any_long_hold_start=self._on_long_hold_start,
            on_any_long_hold_end=self._on_long_hold_end,
        )
        
        # Audio
        print("Initializing audio...")
        self.audio = create_audio_manager()
        
        # Power
        print("Initializing power...")
        self.power = create_power_manager()
        
        # WiFi
        print("Initializing WiFi...")
        self.wifi = create_wifi_manager()
        
        # DATP client (will be initialized after WiFi connect)
        self.client = None
        self.datp_device = DeviceState()
        
        # Device config
        self.device_id = self._load_device_id()
        self.gateway_host = self._load_gateway_host()
        
        # Initial state
        self.datp_device.set_mode("BOOTING")
        self.status_display.show_status("idle", "Starting...")
        
        # Show ready
        self.status_display.show_status("idle", "Ready")
        
        print("Boot complete")
    
    def _load_device_id(self) -> str:
        """Load or generate device ID."""
        # Would load from persistent storage
        # For now, generate from MAC address
        import network
        wlan = network.WLAN(network.STA_IF)
        mac = wlan.config('mac')
        if mac:
            return "stick-" + "".join("{:02x}".format(b) for b in mac[-3:])
        return "stick-001"
    
    def _load_gateway_host(self) -> str:
        """Load gateway host from config."""
        # Would load from persistent storage
        return "0.0.0.0"  # Default placeholder when the runtime cannot read an IP.
    
    def connect_wifi(self, ssid: str = None, password: str = None) -> bool:
        """Connect to WiFi."""
        if ssid:
            self.wifi.configure(ssid, password)
        
        # Try to connect
        if self.wifi.connect():
            rssi = self.wifi.get_rssi()
            self.datp_device.set_wifi_rssi(rssi)
            return True
        return False
    
    def connect_gateway(self) -> bool:
        """Connect to DATP gateway."""
        if not self.wifi.is_connected():
            print("Cannot connect to gateway: no WiFi")
            return False
        
        self.client = DATPClient(
            device_id=self.device_id,
            gateway_host=self.gateway_host,
            device_type="stickS3",
            firmware="oi-fw/0.1.0"
        )
        
        # Set up command handlers to use firmware methods
        self.client._command_handlers["display.show_status"] = self._handle_display_status
        self.client._command_handlers["display.show_card"] = self._handle_display_card
        self.client._command_handlers["audio.cache.put_begin"] = self._handle_audio_cache_begin
        self.client._command_handlers["audio.cache.put_chunk"] = self._handle_audio_cache_chunk
        self.client._command_handlers["audio.cache.put_end"] = self._handle_audio_cache_end
        self.client._command_handlers["audio.play"] = self._handle_audio_play
        self.client._command_handlers["audio.stop"] = self._handle_audio_stop
        self.client._command_handlers["device.set_brightness"] = self._handle_brightness
        self.client._command_handlers["device.set_volume"] = self._handle_volume
        self.client._command_handlers["device.mute_until"] = self._handle_mute_until
        self.client._command_handlers["wifi.configure"] = self._handle_wifi_config
        self.client._command_handlers["storage.format"] = self._handle_storage_format
        
        if self.client.connect():
            self.datp_device.set_mode("READY")
            self.status_display.show_status("idle", "Online")
            return True
        
        return False
    
    # Button event handlers
    def _on_button_pressed(self, name: str):
        """Handle button pressed."""
        print("Button pressed:", name)
        
        if self.client and self.client.connection_state == 3:  # Connected
            self.client.send_event("button.pressed", button=name)
    
    def _on_button_released(self, name: str):
        """Handle button released."""
        print("Button released:", name)
        
        if self.client and self.client.connection_state == 3:
            self.client.send_event("button.released", button=name)
    
    def _on_long_hold_start(self, name: str, duration_ms: int):
        """Handle long hold started."""
        print("Long hold started:", name, duration_ms)
        
        if self.datp_device.can_record():
            self.datp_device.set_mode("RECORDING")
            self.status_display.show_status("listening", "Recording...")
            
            # Start audio recording
            self.audio.start_recording()
            
            # Send event
            if self.client and self.client.connection_state == 3:
                stream_id = self.datp_device.get_current_stream_id()
                self.client.send_event("audio.recording_started", stream_id=stream_id)
    
    def _on_long_hold_end(self, name: str, duration_ms: int):
        """Handle long hold ended."""
        print("Long hold ended:", name, duration_ms)
        
        if self.datp_device.get_mode() == "RECORDING":
            # Stop recording
            self.datp_device.set_mode("UPLOADING")
            audio_data = self.audio.stop_recording()
            
            # Send recording finished event
            if self.client and self.client.connection_state == 3:
                stream_id = self.datp_device.get_current_stream_id()
                duration = self.audio.get_recording_duration_ms()
                self.client.send_audio_recording_finished(stream_id, duration)
                # In real implementation, would send audio chunks here
            
            # Transition to thinking
            self.datp_device.set_mode("THINKING")
            self.status_display.show_status("thinking", "Processing...")
    
    # Command handlers
    def _handle_display_status(self, args: dict):
        """Handle display.show_status command."""
        state = args.get("state", "idle")
        label = args.get("label", "")
        self.status_display.show_status(state, label)
    
    def _handle_display_card(self, args: dict):
        """Handle display.show_card command."""
        title = args.get("title", "")
        options = args.get("options", [])
        self.card_display.show_card(title, "", options)
    
    def _handle_audio_cache_begin(self, args: dict):
        """Handle audio.cache.put_begin command."""
        response_id = args.get("response_id")
        format = args.get("format", "wav_pcm16")
        sample_rate = args.get("sample_rate", 22050)
        bytes = args.get("bytes", 0)
        label = args.get("label", "")
        
        self.audio.cache_audio_begin(response_id, format, sample_rate, bytes, label)
    
    def _handle_audio_cache_chunk(self, args: dict):
        """Handle audio.cache.put_chunk command."""
        response_id = args.get("response_id")
        seq = args.get("seq", 0)
        data_b64 = args.get("data_b64", "")
        
        self.audio.cache_audio_chunk(response_id, seq, data_b64)
    
    def _handle_audio_cache_end(self, args: dict):
        """Handle audio.cache.put_end command."""
        response_id = args.get("response_id")
        sha256 = args.get("sha256")
        
        self.audio.cache_audio_end(response_id, sha256)
        
        # Transition to RESPONSE_CACHED
        if self.datp_device.get_mode() == "THINKING":
            self.datp_device.set_mode("RESPONSE_CACHED")
            self.status_display.show_status("response_cached", "Response ready")
    
    def _handle_audio_play(self, args: dict):
        """Handle audio.play command."""
        response_id = args.get("response_id", "latest")
        
        if self.audio.play(response_id):
            self.datp_device.set_mode("PLAYING")
            self.status_display.show_status("playing", "Playing...")
    
    def _handle_audio_stop(self, args: dict):
        """Handle audio.stop command."""
        self.audio.stop()
        
        # Return to READY or RESPONSE_CACHED
        mode = self.datp_device.get_mode()
        if mode == "PLAYING":
            if self.audio.get_cached_audio():
                self.datp_device.set_mode("RESPONSE_CACHED")
            else:
                self.datp_device.set_mode("READY")
            self.status_display.show_status("idle", "Ready")
    
    def _handle_brightness(self, args: dict):
        """Handle device.set_brightness command."""
        value = args.get("value", 255)
        self.display.set_brightness(value)
    
    def _handle_volume(self, args: dict):
        """Handle device.set_volume command."""
        level = args.get("level", 50)
        self.audio.set_volume(level)
    
    def _handle_mute_until(self, args: dict):
        """Handle device.mute_until command."""
        until = args.get("until")
        self.datp_device.set_muted_until(until)
        
        if until:
            self.datp_device.set_mode("MUTED")
            self.status_display.show_status("muted", "Muted")
    
    def _handle_wifi_config(self, args: dict):
        """Handle wifi.configure command."""
        ssid = args.get("ssid")
        password = args.get("password")
        
        self.wifi.configure(ssid, password)
        self.wifi.connect()
    
    def _handle_storage_format(self, args: dict):
        """Handle storage.format command."""
        self.audio.clear_cache()
    
    def update(self):
        """Update firmware. Call this in main loop."""
        # Update buttons
        self.buttons.update()
        
        # Update power
        self.power.update()
        
        # Update WiFi
        self.wifi.update()
        
        # Update status display (animation)
        self.status_display.update()
        
        # Poll DATP client
        if self.client:
            self.client.poll()
            
            # Send periodic state reports
            # (would implement timer-based state reports)


# Global firmware instance
_firmware = None


def init():
    """Initialize firmware on boot."""
    global _firmware
    _firmware = Firmware()
    return _firmware


def get():
    """Get firmware instance."""
    global _firmware
    return _firmware


# Initialize on boot
if __name__ == "__main__":
    init()
