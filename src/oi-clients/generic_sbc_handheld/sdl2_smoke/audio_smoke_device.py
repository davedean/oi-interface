#!/usr/bin/env python3
"""Audio playback smoke test for RG351P (AmberELEC).

This script should be run on the device, either via SSH or from the terminal.
It uses the existing oi_client.audio module to play a short beep.

Usage:
    python3 audio_smoke_device.py

Environment:
    Should be run from /storage/roms/ports/OiSmokeTest/ or similar location.
    PYTHONPATH must include /storage/roms/ports/Oi/oi_client and /storage/roms/ports/Oi
"""

import os
import sys
import time
import math

# Add the Oi client directory to path
OI_CLIENT_PATH = "/storage/roms/ports/Oi/oi_client"
if os.path.isdir(OI_CLIENT_PATH) and OI_CLIENT_PATH not in sys.path:
    sys.path.insert(0, OI_CLIENT_PATH)

# Also add parent directory for libs
OI_ROOT = "/storage/roms/ports/Oi"
if os.path.isdir(OI_ROOT) and OI_ROOT not in sys.path:
    sys.path.insert(0, OI_ROOT)

try:
    from audio import HandheldAudio
except ImportError as e:
    print(f"ERROR: Cannot import HandheldAudio: {e}")
    print("Make sure the oi_client package is installed at /storage/roms/ports/Oi/oi_client")
    sys.exit(1)


def generate_pcm16_sine(frequency: float, duration: float, sample_rate: int = 16000) -> bytes:
    """Generate mono PCM16LE sine wave."""
    total_samples = int(duration * sample_rate)
    data = bytearray(total_samples * 2)  # 2 bytes per sample (S16LE)
    for i in range(total_samples):
        sample = int(32767 * 0.3 * math.sin(2 * math.pi * frequency * i / sample_rate))
        # clamp to S16 range
        if sample > 32767:
            sample = 32767
        elif sample < -32768:
            sample = -32768
        # pack as signed little-endian
        data[i*2] = sample & 0xFF
        data[i*2 + 1] = (sample >> 8) & 0xFF
    return bytes(data)


def main() -> int:
    print("=== Audio Playback Smoke Test (RG351P) ===")
    
    audio = HandheldAudio()
    
    # Detect audio hardware
    status = audio.detect()
    print(f"Audio status: {status}")
    
    if not status.has_output:
        print("WARNING: Audio output not detected. This may be a false negative.")
        print("Proceeding anyway...")
    
    # Generate a short beep (440 Hz, 1 second) at 16 kHz (common for voice)
    print("Generating 440 Hz sine wave (1 second)...")
    pcm = generate_pcm16_sine(440.0, 1.0, sample_rate=16000)
    
    # Save as WAV file using module's method
    wav_path = audio.save_wav(pcm, sample_rate=16000)
    print(f"Created WAV file: {wav_path}")
    
    # Play the file
    print("Playing audio via aplay...")
    success = audio.play(wav_path)
    if not success:
        print("FAIL: play() returned False. aplay may not be installed or failed.")
        # Clean up
        try:
            os.unlink(wav_path)
        except:
            pass
        return 1
    
    # Wait for playback to finish (poll is_playing)
    print("Waiting for playback to finish...")
    for i in range(30):  # up to 3 seconds
        time.sleep(0.1)
        if not audio.is_playing():
            print("Playback finished.")
            break
    else:
        print("Playback may still be running (timeout).")
    
    # Stop any playback (just in case)
    audio.stop()
    
    # Clean up
    try:
        os.unlink(wav_path)
    except:
        pass
    
    print("SUCCESS: Audio playback test passed.")
    print("You should have heard a 1-second beep from the device's speaker/headphone jack.")
    return 0


if __name__ == "__main__":
    sys.exit(main())