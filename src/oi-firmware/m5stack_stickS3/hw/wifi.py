"""
WiFi Connectivity for M5Stack StickS3.

This module handles WiFi connection management:
- Connect to WiFi network
- Maintain connection
- Reconnection on disconnect
- WiFi status reporting
"""

import network
import utime


# WiFi status codes
STATUS_IDLE = 0
STATUS_CONNECTING = 1
STATUS_CONNECTED = 2
STATUS_DISCONNECTED = 3
STATUS_FAILED = 4


class WiFiManager:
    """
    WiFi connection manager for M5Stack StickS3.
    
    Handles WiFi connectivity, reconnection, and status reporting.
    """
    
    def __init__(self):
        """Initialize WiFi manager."""
        # Create WLAN interface
        self._wlan = network.WLAN(network.STA_IF)
        
        # Configuration
        self._ssid = None
        self._password = None
        
        # State
        self._connected = False
        self._connecting = False
        
        # Callbacks
        self._on_connected = None
        self._on_disconnected = None
        self._on_failed = None
    
    def set_callbacks(self, on_connected=None, on_disconnected=None, on_failed=None):
        """Set WiFi event callbacks."""
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_failed = on_failed
    
    def configure(self, ssid: str, password: str):
        """
        Configure WiFi credentials.
        
        Args:
            ssid: WiFi network name
            password: WiFi password
        """
        self._ssid = ssid
        self._password = password
    
    def connect(self, ssid: str = None, password: str = None, timeout_ms: int = 10000) -> bool:
        """
        Connect to WiFi network.
        
        Args:
            ssid: WiFi network name (uses configured if None)
            password: WiFi password (uses configured if None)
            timeout_ms: Connection timeout in milliseconds
        
        Returns:
            True if connected, False otherwise.
        """
        if ssid:
            self._ssid = ssid
        if password:
            self._password = password
        
        if not self._ssid or not self._password:
            print("WiFi: No credentials configured")
            return False
        
        # Activate interface
        if not self._wlan.active():
            self._wlan.active(True)
        
        self._connecting = True
        print("WiFi: Connecting to {}".format(self._ssid))
        
        # Connect
        self._wlan.connect(self._ssid, self._password)
        
        # Wait for connection
        start = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), start) < timeout_ms:
            if self._wlan.isconnected():
                self._connected = True
                self._connecting = False
                print("WiFi: Connected, IP: {}".format(self._wlan.ifconfig()[0]))
                
                if self._on_connected:
                    self._on_connected(self._ssid, self.get_rssi())
                
                return True
            
            utime.sleep_ms(100)
        
        # Connection failed
        self._connected = False
        self._connecting = False
        print("WiFi: Connection failed")
        
        if self._on_failed:
            self._on_failed(self._ssid)
        
        return False
    
    def disconnect(self):
        """Disconnect from WiFi network."""
        if self._connected:
            self._wlan.disconnect()
            self._connected = False
            print("WiFi: Disconnected")
            
            if self._on_disconnected:
                self._on_disconnected()
    
    def reconnect(self) -> bool:
        """Reconnect using saved credentials."""
        if self._ssid and self._password:
            return self.connect()
        return False
    
    def is_connected(self) -> bool:
        """Check if connected to WiFi."""
        self._connected = self._wlan.isconnected()
        return self._connected
    
    def get_rssi(self) -> int:
        """
        Get WiFi signal strength.
        
        Returns:
            RSSI in dBm (negative value, closer to 0 is stronger).
        """
        if not self._connected:
            return -100
        
        try:
            # Some ports may not support this
            return self._wlan.status('rssi')
        except:
            return -100
    
    def get_ip(self) -> str:
        """
        Get device IP address.
        
        Returns:
            IP address as string, or None if not connected.
        """
        if self._connected:
            return self._wlan.ifconfig()[0]
        return None
    
    def get_status(self) -> dict:
        """Get complete WiFi status."""
        return {
            "connected": self.is_connected(),
            "ssid": self._ssid if self._connected else None,
            "rssi": self.get_rssi(),
            "ip": self.get_ip(),
        }
    
    def scan_networks(self) -> list:
        """
        Scan for available networks.
        
        Returns:
            List of network info dicts.
        """
        if not self._wlan.active():
            self._wlan.active(True)
        
        networks = self._wlan.scan()
        
        result = []
        for net in networks:
            result.append({
                "ssid": net[0].decode() if isinstance(net[0], bytes) else net[0],
                "bssid": net[1].hex() if isinstance(net[1], bytes) else net[1],
                "channel": net[2],
                "rssi": net[3],
                "security": net[4],
                "hidden": net[5],
            })
        
        return result
    
    def update(self):
        """Update WiFi state. Check for disconnection and reconnect if needed."""
        if self._connected and not self._wlan.isconnected():
            # Lost connection
            self._connected = False
            print("WiFi: Connection lost")
            
            if self._on_disconnected:
                self._on_disconnected()
            
            # Attempt reconnection
            self.reconnect()


def create_wifi_manager() -> WiFiManager:
    """Factory function to create a WiFi manager."""
    return WiFiManager()


# Example usage:
#
# wifi = create_wifi_manager()
# wifi.set_callbacks(
#     on_connected=lambda ssid, rssi: print("Connected to", ssid, "RSSI:", rssi),
#     on_disconnected=lambda: print("Disconnected"),
# )
#
# wifi.configure("MyNetwork", "mypassword")
# if wifi.connect():
#     print("IP:", wifi.get_ip())