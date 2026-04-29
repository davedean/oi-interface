"""
Power Management for M5Stack StickS3.

This module handles power-related functionality:
- Battery voltage monitoring
- Charging state detection
- Power button handling
- System power control
"""

import machine
import utime


# ADC pin for battery voltage
PIN_BAT_ADC = 1  # GPIO 1 (or appropriate ADC channel)

# Voltage thresholds (may need calibration)
VOLTAGE_MAX = 4.2  # Fully charged LiPo
VOLTAGE_MIN = 3.0  # Fully discharged
VOLTAGE_FULL = 3.9  # Consider "full" for percentage calculation

# Percentage thresholds
BATTERY_FULL = 100
BATTERY_LOW = 20
BATTERY_CRITICAL = 10


class PowerManager:
    """
    Power management for M5Stack StickS3.
    
    Handles battery monitoring, charging detection, and power control.
    """
    
    def __init__(self, adc_pin: int = None):
        """
        Initialize power manager.
        
        Args:
            adc_pin: ADC pin number for battery voltage. If None, uses default.
        """
        self.adc_pin = adc_pin or PIN_BAT_ADC
        
        # Initialize ADC if available
        try:
            self._adc = machine.ADC(machine.Pin(self.adc_pin))
            self._adc.atten(machine.ADC.ATTN_11DB)  # Full range 0-3.3V
        except Exception as e:
            print("ADC initialization failed:", e)
            self._adc = None
        
        # Charging pin (if available)
        self._charging = False
        self._usb_connected = False
        
        # Battery state
        self._battery_percent = 100
        self._voltage = 0.0
        
        # Power callback
        self._on_battery_low = None
        self._on_battery_critical = None
        self._on_charging_started = None
        self._on_charging_stopped = None
        
        # Last alert times to avoid repeated alerts
        self._low_alert_fired = False
        self._critical_alert_fired = False
    
    def set_callbacks(self, on_battery_low=None, on_battery_critical=None,
                     on_charging_started=None, on_charging_stopped=None):
        """Set power event callbacks."""
        self._on_battery_low = on_battery_low
        self._on_battery_critical = on_battery_critical
        self._on_charging_started = on_charging_started
        self._on_charging_stopped = on_charging_stopped
    
    def read_voltage(self) -> float:
        """
        Read battery voltage.
        
        Returns:
            Battery voltage in volts, or 0.0 if reading failed.
        """
        if not self._adc:
            return 0.0
        
        try:
            # Read multiple samples and average
            samples = []
            for _ in range(10):
                samples.append(self._adc.read())
                utime.sleep_ms(1)
            
            avg = sum(samples) // len(samples)
            
            # Convert ADC value to voltage
            # ADC is 12-bit (0-4095) with 3.3V reference
            # Need to account for voltage divider if present
            # Assuming simple voltage divider: V_bat = V_adc * (R1+R2)/R2
            # For M5StickS3, typically ~2x divider
            
            voltage = (avg / 4095) * 3.3 * 2.0  # Adjust multiplier as needed
            
            self._voltage = voltage
            return voltage
        except Exception as e:
            print("Voltage read error:", e)
            return 0.0
    
    def get_battery_percent(self) -> int:
        """
        Get battery percentage.
        
        Returns:
            Battery percentage (0-100).
        """
        voltage = self.read_voltage()
        
        if voltage <= 0:
            return self._battery_percent
        
        # Calculate percentage based on voltage range
        if voltage >= VOLTAGE_MAX:
            percent = 100
        elif voltage <= VOLTAGE_MIN:
            percent = 0
        else:
            percent = int((voltage - VOLTAGE_MIN) / (VOLTAGE_MAX - VOLTAGE_MIN) * 100)
        
        self._battery_percent = percent
        return percent
    
    def is_charging(self) -> bool:
        """
        Check if device is currently charging.
        
        Returns:
            True if charging, False otherwise.
        """
        # This would need actual hardware detection
        # For now, return a placeholder
        # Could check USB detect pin or charging IC status
        return self._charging
    
    def is_usb_connected(self) -> bool:
        """
        Check if USB power is connected.
        
        Returns:
            True if USB connected, False otherwise.
        """
        return self._usb_connected
    
    def get_power_state(self) -> dict:
        """Get complete power state."""
        return {
            "battery_percent": self.get_battery_percent(),
            "voltage": self._voltage,
            "charging": self.is_charging(),
            "usb_connected": self.is_usb_connected(),
        }
    
    def update(self):
        """Update power state and fire callbacks if needed."""
        percent = self.get_battery_percent()
        
        # Check for low battery
        if percent <= BATTERY_LOW and not self._low_alert_fired:
            if self._on_battery_low:
                self._on_battery_low(percent)
            self._low_alert_fired = True
        
        # Reset low alert when battery recovers
        if percent > BATTERY_LOW:
            self._low_alert_fired = False
        
        # Check for critical battery
        if percent <= BATTERY_CRITICAL and not self._critical_alert_fired:
            if self._on_battery_critical:
                self._on_battery_critical(percent)
            self._critical_alert_fired = True
        
        # Reset critical alert when battery recovers
        if percent > BATTERY_CRITICAL:
            self._critical_alert_fired = False
    
    def shutdown(self):
        """Shutdown the device."""
        # This would need hardware-specific implementation
        # Could disable power to peripherals, enter deep sleep, etc.
        print("Shutdown requested")
    
    def reboot(self):
        """Reboot the device."""
        print("Reboot requested")
        machine.reset()


def create_power_manager(adc_pin: int = None) -> PowerManager:
    """Factory function to create a power manager."""
    return PowerManager(adc_pin)