"""
DATP WebSocket Client for M5Stack StickS3 firmware.

This module implements the WebSocket client that connects to oi-gateway
and handles the DATP protocol communication.
"""

import ujson
import usocket
import network
import ussl
import gc
import utime


# For testing on host (MicroPython doesn't have websocket module by default)
try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False


from . import messages
from .state import DeviceState


# Connection states
STATE_DISCONNECTED = 0
STATE_CONNECTING = 1
STATE_HELLO_SENT = 2
STATE_CONNECTED = 3
STATE_RECONNECTING = 4


class DATPClient:
    """
    DATP WebSocket client for device-to-gateway communication.
    
    Handles:
    - WebSocket connection to gateway
    - Hello handshake
    - Event and audio chunk sending
    - Command receiving and acknowledgment
    - Automatic reconnection
    """
    
    def __init__(self, device_id: str, gateway_host: str, gateway_port: int = 8787,
                 device_type: str = "stickS3", firmware: str = "oi-fw/0.1.0"):
        """
        Initialize the DATP client.
        
        Args:
            device_id: Unique device identifier
            gateway_host: Gateway hostname or IP
            gateway_port: Gateway WebSocket port
            device_type: Device type string
            firmware: Firmware version string
        """
        self.device_id = device_id
        self.gateway_host = gateway_host
        self.gateway_port = gateway_port
        self.device_type = device_type
        self.firmware = firmware
        
        self.ws = None
        self.connection_state = STATE_DISCONNECTED
        self.session_id = None
        self.server_time = None
        
        # State machine
        self.device_state = DeviceState()
        
        # Reconnection
        self.reconnect_delay = 1  # Start with 1 second
        self.max_reconnect_delay = 30
        self.max_reconnect_attempts = 10
        self.reconnect_count = 0
        
        # Message handlers
        self._command_handlers = {}
        self._event_callbacks = []
        
        # Audio streaming
        self._current_stream_id = None
        self._audio_chunk_seq = 0
        
        # Register default command handlers
        self._register_default_handlers()
    
    def _register_default_handlers(self):
        """Register default command handlers."""
        self._command_handlers = {
            "display.show_status": self._handle_display_show_status,
            "display.show_card": self._handle_display_show_card,
            "audio.cache.put_begin": self._handle_audio_cache_put_begin,
            "audio.cache.put_chunk": self._handle_audio_cache_put_chunk,
            "audio.cache.put_end": self._handle_audio_cache_put_end,
            "audio.play": self._handle_audio_play,
            "audio.stop": self._handle_audio_stop,
            "device.set_brightness": self._handle_device_set_brightness,
            "device.set_volume": self._handle_device_set_volume,
            "device.set_led": self._handle_device_set_led,
            "device.mute_until": self._handle_device_mute_until,
            "device.reboot": self._handle_device_reboot,
            "device.shutdown": self._handle_device_shutdown,
            "wifi.configure": self._handle_wifi_configure,
            "storage.format": self._handle_storage_format,
        }
    
    def set_command_handler(self, op: str, handler):
        """Register a custom command handler."""
        self._command_handlers[op] = handler
    
    def register_event_callback(self, callback):
        """Register a callback for incoming events (for testing)."""
        self._event_callbacks.append(callback)
    
    def get_capabilities(self) -> dict:
        """Get device capabilities for hello message."""
        return {
            "audio_in": True,
            "audio_out": True,
            "display": "st7789_135x240",
            "buttons": ["main", "a", "b"],
            "commands_supported": list(self._command_handlers.keys())
        }
    
    def get_state_report(self) -> dict:
        """Get current state for hello and state reports."""
        state = self.device_state.get_state()
        return {
            "mode": state["mode"],
            "battery_percent": state["battery_percent"],
            "charging": state["charging"],
            "wifi_rssi": state["wifi_rssi"],
            "heap_free": gc.mem_alloc() if hasattr(gc, 'mem_alloc') else 0,
            "uptime_s": state["uptime_s"],
            "audio_cache_used_bytes": state.get("audio_cache_used_bytes", 0),
            "muted_until": state.get("muted_until")
        }
    
    def connect(self) -> bool:
        """
        Establish WebSocket connection to gateway.
        
        Returns:
            True if connection successful
        """
        self.connection_state = STATE_CONNECTING
        
        try:
            # Build WebSocket URL
            ws_url = "ws://{}:{}/datp".format(self.gateway_host, self.gateway_port)
            
            if HAS_WEBSOCKET:
                # Use MicroPython websocket module
                self.ws = websocket.WebSocket()
                self.ws.connect(ws_url)
            else:
                # Fallback: use raw socket (simplified WebSocket)
                self._connect_raw_socket(ws_url)
            
            # Send hello message
            hello_msg = messages.build_hello(
                device_id=self.device_id,
                device_type=self.device_type,
                firmware=self.firmware,
                capabilities=self.get_capabilities(),
                state=self.get_state_report(),
                resume_token=None,
                nonce=None
            )
            
            self._send_raw(hello_msg)
            self.connection_state = STATE_HELLO_SENT
            
            # Wait for hello_ack
            response = self._receive_raw()
            if response:
                self._handle_message(response)
            
            if self.session_id:
                self.connection_state = STATE_CONNECTED
                self.device_state.set_mode("READY")
                self.reconnect_count = 0
                return True
            
            return False
            
        except Exception as e:
            print("Connection failed: {}".format(e))
            self.connection_state = STATE_DISCONNECTED
            return False
    
    def _connect_raw_socket(self, ws_url: str):
        """Connect using raw socket (fallback when websocket module unavailable)."""
        # Parse host and port from ws://host:port/path
        # Simple version: expects ws://host:port format
        import ure
        match = ure.match(r"ws://([^:]+):(\d+)", ws_url)
        if not match:
            raise ValueError("Invalid WebSocket URL")
        
        host = match.group(1)
        port = int(match.group(2))
        
        # Create socket
        addr = usocket.getaddrinfo(host, port)[0]
        sock = usocket.socket(usocket.AF_INET, usocket.SOCK_STREAM)
        sock.connect(addr)
        
        # Simple WebSocket handshake
        sock.write(b"GET /datp HTTP/1.1\r\n")
        sock.write(b"Host: {}:{}\r\n".format(host.encode(), port))
        sock.write(b"Upgrade: websocket\r\n")
        sock.write(b"Connection: Upgrade\r\n")
        sock.write(b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n")
        sock.write(b"Sec-WebSocket-Version: 13\r\n")
        sock.write(b"\r\n")
        
        # Read response (simplified - just get socket)
        self._raw_socket = sock
        self._raw_socket_buf = b""
    
    def _send_raw(self, data: str):
        """Send data over WebSocket."""
        if HAS_WEBSOCKET and self.ws:
            self.ws.send(data)
        elif hasattr(self, '_raw_socket'):
            # Send as WebSocket text frame
            # For simplicity, just send raw (gateway may handle)
            self._raw_socket.write(data.encode())
    
    def _receive_raw(self) -> str:
        """Receive data from WebSocket."""
        if HAS_WEBSOCKET and self.ws:
            try:
                return self.ws.recv()
            except:
                return None
        elif hasattr(self, '_raw_socket'):
            # Simplified - read from socket
            try:
                data = self._raw_socket.read(1024)
                if data:
                    return data.decode()
            except:
                return None
        return None
    
    def _handle_message(self, data: str):
        """Handle incoming message."""
        try:
            msg = messages.parse_message(data)
        except ValueError as e:
            print("Failed to parse message: {}".format(e))
            return
        
        msg_type = messages.get_message_type(msg)
        
        if msg_type == messages.TYPE_HELLO_ACK:
            self._handle_hello_ack(msg)
        elif msg_type == messages.TYPE_COMMAND:
            self._handle_command(msg)
        elif msg_type == messages.TYPE_ERROR:
            self._handle_error(msg)
        else:
            print("Unknown message type: {}".format(msg_type))
    
    def _handle_hello_ack(self, msg: dict):
        """Handle hello acknowledgment."""
        payload = messages.get_message_payload(msg)
        self.session_id = payload.get("session_id")
        self.server_time = payload.get("server_time")
        print("Connected: session_id={}".format(self.session_id))
    
    def _handle_command(self, msg: dict):
        """Handle incoming command."""
        command_id = msg.get("id")
        payload = messages.get_message_payload(msg)
        op = payload.get("op")
        args = payload.get("args", {})
        
        print("Command: {} {}".format(op, args))
        
        # Check if device is in correct state for this command
        if not self.device_state.can_handle_command(op):
            self.send_ack(command_id, ok=False,
                        error="Cannot execute {} in {} state".format(
                            op, self.device_state.get_mode()))
            return
        
        # Execute command handler
        handler = self._command_handlers.get(op)
        if handler:
            try:
                result = handler(args)
                self.send_ack(command_id, ok=True)
            except Exception as e:
                self.send_ack(command_id, ok=False, error=str(e))
        else:
            self.send_ack(command_id, ok=False, error="Unknown command: {}".format(op))
    
    def _handle_error(self, msg: dict):
        """Handle error from gateway."""
        payload = messages.get_message_payload(msg)
        code = payload.get("code")
        message = payload.get("message")
        related_id = payload.get("related_id")
        print("Gateway error: {} - {} (related: {})".format(code, message, related_id))
        
        # Handle connection errors
        if code in ("SESSION_EXPIRED", "DEVICE_NOT_FOUND"):
            self._trigger_reconnect()
    
    def send_ack(self, command_id: str, ok: bool, error: str = None):
        """Send acknowledgment for a command."""
        ack_msg = messages.build_ack(self.device_id, command_id, ok, error)
        self._send_raw(ack_msg)
    
    def send_event(self, event: str, **kwargs):
        """Send an event message to gateway."""
        event_msg = messages.build_event(self.device_id, event, **kwargs)
        self._send_raw(event_msg)
    
    def send_audio_chunk(self, stream_id: str, seq: int, data_b64: str,
                        sample_rate: int = 44100, channels: int = 2):
        """Send an audio chunk to gateway."""
        chunk_msg = messages.build_audio_chunk(
            self.device_id, stream_id, seq, "pcm16",
            sample_rate, channels, data_b64
        )
        self._send_raw(chunk_msg)
    
    def send_audio_recording_finished(self, stream_id: str, duration_ms: int):
        """Send recording finished event."""
        event_msg = messages.build_audio_recording_finished(
            self.device_id, stream_id, duration_ms
        )
        self._send_raw(event_msg)
    
    def send_state(self):
        """Send periodic state report."""
        state_msg = messages.build_state(self.device_id, self.get_state_report())
        self._send_raw(state_msg)
    
    def send_error(self, code: str, message: str, related_id: str = None):
        """Send an error message to gateway."""
        error_msg = messages.build_error(self.device_id, code, message, related_id)
        self._send_raw(error_msg)
    
    def _trigger_reconnect(self):
        """Trigger reconnection with exponential backoff."""
        if self.reconnect_count >= self.max_reconnect_attempts:
            print("Max reconnection attempts exceeded")
            self.connection_state = STATE_DISCONNECTED
            self.device_state.set_mode("ERROR")
            return
        
        self.connection_state = STATE_RECONNECTING
        delay = min(self.reconnect_delay * (2 ** self.reconnect_count),
                   self.max_reconnect_delay)
        print("Reconnecting in {} seconds (attempt {}/{})".format(
            delay, self.reconnect_count + 1, self.max_reconnect_attempts))
        
        utime.sleep(delay)
        self.reconnect_count += 1
        self.connect()
    
    def poll(self, timeout_ms: int = 100) -> bool:
        """
        Poll for incoming messages.
        
        Args:
            timeout_ms: Timeout in milliseconds
        
        Returns:
            True if still connected
        """
        if self.connection_state not in (STATE_CONNECTED, STATE_HELLO_SENT):
            return False
        
        try:
            # Non-blocking receive check
            data = self._receive_raw()
            if data:
                self._handle_message(data)
                return True
        except Exception as e:
            print("Poll error: {}".format(e))
            self._trigger_reconnect()
        
        return self.connection_state == STATE_CONNECTED
    
    def disconnect(self):
        """Disconnect from gateway."""
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
        elif hasattr(self, '_raw_socket'):
            try:
                self._raw_socket.close()
            except:
                pass
        
        self.connection_state = STATE_DISCONNECTED
        self.session_id = None
    
    # Default command handlers (to be overridden or enhanced)
    
    def _handle_display_show_status(self, args: dict):
        """Handle display.show_status command."""
        state = args.get("state", "idle")
        label = args.get("label", "")
        # To be implemented with UI module
        print("Display status: {} - {}".format(state, label))
    
    def _handle_display_show_card(self, args: dict):
        """Handle display.show_card command."""
        title = args.get("title", "")
        options = args.get("options", [])
        # To be implemented with UI module
        print("Display card: {} options={}".format(title, options))
    
    def _handle_audio_cache_put_begin(self, args: dict):
        """Handle audio.cache.put_begin command."""
        response_id = args.get("response_id")
        format = args.get("format", "wav_pcm16")
        sample_rate = args.get("sample_rate", 22050)
        bytes = args.get("bytes", 0)
        label = args.get("label", "")
        # To be implemented with audio module
        print("Audio cache begin: {} {} {}Hz {}bytes".format(
            response_id, format, sample_rate, bytes))
    
    def _handle_audio_cache_put_chunk(self, args: dict):
        """Handle audio.cache.put_chunk command."""
        response_id = args.get("response_id")
        seq = args.get("seq", 0)
        data_b64 = args.get("data_b64", "")
        # To be implemented with audio module
        pass
    
    def _handle_audio_cache_put_end(self, args: dict):
        """Handle audio.cache.put_end command."""
        response_id = args.get("response_id")
        sha256 = args.get("sha256")
        # To be implemented with audio module
        print("Audio cache end: {} sha256={}".format(response_id, sha256))
    
    def _handle_audio_play(self, args: dict):
        """Handle audio.play command."""
        response_id = args.get("response_id", "latest")
        # To be implemented with audio module
        print("Audio play: {}".format(response_id))
    
    def _handle_audio_stop(self, args: dict):
        """Handle audio.stop command."""
        # To be implemented with audio module
        print("Audio stop")
    
    def _handle_device_set_brightness(self, args: dict):
        """Handle device.set_brightness command."""
        value = args.get("value", 255)
        # To be implemented with display module
        print("Set brightness: {}".format(value))
    
    def _handle_device_set_volume(self, args: dict):
        """Handle device.set_volume command."""
        level = args.get("level", 50)
        # To be implemented with audio module
        print("Set volume: {}".format(level))
    
    def _handle_device_set_led(self, args: dict):
        """Handle device.set_led command."""
        enabled = args.get("enabled", True)
        # To be implemented with hardware module
        print("Set LED: {}".format(enabled))
    
    def _handle_device_mute_until(self, args: dict):
        """Handle device.mute_until command."""
        until = args.get("until")
        # To be implemented with state module
        print("Mute until: {}".format(until))
    
    def _handle_device_reboot(self, args: dict):
        """Handle device.reboot command."""
        print("Reboot command received")
        # To be implemented
        # import machine
        # machine.reset()
    
    def _handle_device_shutdown(self, args: dict):
        """Handle device.shutdown command."""
        print("Shutdown command received")
        self.device_state.set_mode("OFFLINE")
    
    def _handle_wifi_configure(self, args: dict):
        """Handle wifi.configure command."""
        ssid = args.get("ssid")
        password = args.get("password")
        # To be implemented with WiFi module
        print("WiFi configure: {}".format(ssid))
    
    def _handle_storage_format(self, args: dict):
        """Handle storage.format command."""
        # To be implemented
        print("Storage format")


# Standalone functions for testing (can be used without class)
def create_client(device_id: str, gateway_host: str, **kwargs) -> DATPClient:
    """Factory function to create a DATP client."""
    return DATPClient(device_id, gateway_host, **kwargs)