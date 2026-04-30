#!/usr/bin/env python3
"""Test DATP connection and prompt sending."""

import asyncio
import json
import os
import sys
import traceback

# Setup environment like __main__.py
os.environ.setdefault("PYSDL2_DLL_PATH", "/usr/lib")
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR_LIB = os.path.join(_SCRIPT_DIR, "lib")
if os.path.isdir(VENDOR_LIB) and VENDOR_LIB not in sys.path:
    sys.path.insert(0, VENDOR_LIB)

# PortMaster fallback
if "sdl2" not in sys.modules:
    pm_exlibs = "/storage/roms/ports/PortMaster/exlibs"
    if os.path.isdir(pm_exlibs) and pm_exlibs not in sys.path:
        sys.path.insert(0, pm_exlibs)

# Add Oi client path
OI_CLIENT_PATH = "/storage/roms/ports/Oi/oi_client"
if os.path.isdir(OI_CLIENT_PATH) and OI_CLIENT_PATH not in sys.path:
    sys.path.insert(0, OI_CLIENT_PATH)

async def test():
    from datp import DatpClient
    
    gateway = "ws://192.168.1.85:8787/datp"
    device_id = "rg351p-test"
    device_type = "sbc-handheld"
    
    # Mock capabilities (similar to what app would send)
    capabilities = {
        "input": ["buttons", "dpad", "confirm_buttons"],
        "output": ["screen", "cached_audio"],
        "sensors": ["battery", "wifi_rssi"],
        "commands_supported": [
            "display.show_status",
            "display.show_card",
            "display.show_progress",
            "display.show_response_delta",
            "audio.cache.put_begin",
            "audio.cache.put_chunk",
            "audio.cache.put_end",
            "audio.play",
            "audio.stop",
            "device.set_brightness",
            "device.mute_until",
        ],
        "display_width": 40,
        "display_height": 20,
        "has_audio_input": False,
        "has_audio_output": True,
        "supports_text_input": False,
        "supports_confirm_buttons": True,
        "supports_scrolling_cards": True,
        "supports_voice": False,
        "max_spoken_duration_s": 120
    }
    
    client = DatpClient(
        gateway=gateway,
        device_id=device_id,
        device_type=device_type,
        capabilities=capabilities,
    )
    
    print(f"Connecting to {gateway}...")
    try:
        connected = await client.connect()
        if not connected:
            print("Connection failed.")
            return 1
        
        print(f"Connected. Session ID: {client._session_id}")
        
        # Send a test prompt
        print("Sending text prompt...")
        await client.send_text_prompt("What time is it?")
        print("Prompt sent.")
        
        # Wait for a few seconds to receive any commands
        print("Waiting for commands (5 seconds)...")
        for _ in range(10):
            await asyncio.sleep(0.5)
            cmds = client.get_commands()
            if cmds:
                print(f"Received {len(cmds)} commands:")
                for cmd in cmds:
                    print(f"  {cmd.get('op', 'unknown')}")
        
        # Graceful disconnect
        await client.disconnect()
        print("Disconnected.")
        return 0
        
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))