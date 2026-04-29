"""
Main event loop for M5Stack StickS3 firmware.

This module runs the main firmware loop that:
- Processes button events
- Handles audio recording/playback
- Communicates with gateway via DATP
- Updates display
"""

import utime
import gc


# Import boot module to get firmware instance
from boot import init, get


def main():
    """
    Main firmware loop.
    """
    # Initialize firmware
    print("Starting Oi Firmware v0.1.0...")
    firmware = init()
    
    # Main loop
    loop_count = 0
    state_report_interval = 30000  # Send state every 30 seconds
    last_state_report = utime.ticks_ms()
    
    print("Entering main loop...")
    
    while True:
        try:
            # Update firmware (buttons, power, wifi, display, datp)
            firmware.update()
            
            # Handle audio playback in progress
            if firmware.audio.is_playing():
                firmware.audio.write_audio_chunk()
            
            # Handle audio recording in progress
            if firmware.audio.is_recording():
                chunk = firmware.audio.read_audio_chunk()
                # Would send chunk to gateway in real implementation
            
            # Periodic state report
            now = utime.ticks_ms()
            if utime.ticks_diff(now, last_state_report) > state_report_interval:
                if firmware.client and firmware.client.connection_state == 3:
                    # Get current state from datp_device
                    state = firmware.datp_device.get_state()
                    state["heap_free"] = gc.mem_free()
                    firmware.client.send_state()
                last_state_report = now
            
            # Check connection state and reconnect if needed
            if firmware.client:
                if firmware.client.connection_state == 0:  # Disconnected
                    firmware.status_display.show_status("offline", "Reconnecting...")
                    # Would attempt reconnection here
            
            # Sleep a bit to avoid busy loop
            utime.sleep_ms(10)
            
            # Periodically run garbage collection
            loop_count += 1
            if loop_count >= 1000:
                gc.collect()
                loop_count = 0
                
        except Exception as e:
            print("Main loop error:", e)
            utime.sleep_ms(1000)


# Entry point
if __name__ == "__main__":
    main()