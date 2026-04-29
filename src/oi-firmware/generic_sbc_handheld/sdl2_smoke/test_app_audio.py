#!/usr/bin/env python3
"""Test audio integration as used by the HandheldApp.

Simulates the audio.cache.put_end command handling.
"""

import os
import sys
import math
import time

# Add the Oi client directory to path
OI_CLIENT_PATH = "/storage/roms/ports/Oi/oi_client"
if os.path.isdir(OI_CLIENT_PATH) and OI_CLIENT_PATH not in sys.path:
    sys.path.insert(0, OI_CLIENT_PATH)
OI_ROOT = "/storage/roms/ports/Oi"
if os.path.isdir(OI_ROOT) and OI_ROOT not in sys.path:
    sys.path.insert(0, OI_ROOT)

try:
    from audio import HandheldAudio
except ImportError as e:
    print(f"ERROR: Cannot import HandheldAudio: {e}")
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


def test_audio_cache_put_end():
    """Simulate audio.cache.put_end command."""
    print("=== Simulating audio.cache.put_end command ===")
    audio = HandheldAudio()
    
    # Generate some PCM data (like the gateway would send in chunks)
    pcm_data = generate_pcm16_sine(523.25, 1.5, sample_rate=16000)  # C5 note
    
    # Save as WAV (as done in HandheldApp._handle_command)
    wav_path = audio.save_wav(pcm_data, sample_rate=16000)
    print(f"Saved WAV: {wav_path}")
    
    # Play it (as done in HandheldApp._handle_command)
    print("Playing via audio.play()...")
    success = audio.play(wav_path)
    print(f"play() returned: {success}")
    
    # Wait for playback
    for i in range(20):
        time.sleep(0.1)
        if not audio.is_playing():
            print("Playback finished.")
            break
    else:
        print("Playback still running (timeout).")
    
    # Clean up
    try:
        os.unlink(wav_path)
    except:
        pass
    
    return success


def test_audio_play_latest():
    """Simulate audio.play command with 'latest' response_id."""
    print("\n=== Simulating audio.play command (latest) ===")
    audio = HandheldAudio()
    
    # Generate and save two different tones
    pcm1 = generate_pcm16_sine(440.0, 1.0, sample_rate=16000)
    wav1 = audio.save_wav(pcm1, sample_rate=16000)
    print(f"Created first WAV: {wav1}")
    
    pcm2 = generate_pcm16_sine(587.33, 1.0, sample_rate=16000)  # D5
    wav2 = audio.save_wav(pcm2, sample_rate=16000)
    print(f"Created second WAV: {wav2}")
    
    # Simulate _response_audio dict
    response_audio = {
        "resp_1": str(wav1),
        "resp_2": str(wav2),
    }
    
    # Play latest (second)
    latest_wav = list(response_audio.values())[-1]
    if os.path.exists(latest_wav):
        print(f"Playing latest WAV: {latest_wav}")
        success = audio.play(latest_wav)
        print(f"play() returned: {success}")
        
        # Wait a bit
        time.sleep(1.2)
        audio.stop()
    else:
        print("ERROR: Latest WAV doesn't exist")
        success = False
    
    # Clean up
    for wav in [wav1, wav2]:
        try:
            os.unlink(wav)
        except:
            pass
    
    return success


def main() -> int:
    print("Testing HandheldApp audio integration")
    
    # Test 1: audio.cache.put_end simulation
    if not test_audio_cache_put_end():
        print("FAIL: audio.cache.put_end simulation failed")
        return 1
    
    # Test 2: audio.play with latest
    if not test_audio_play_latest():
        print("FAIL: audio.play latest simulation failed")
        return 1
    
    print("\nSUCCESS: All audio integration tests passed")
    print("You should have heard two different beeps.")
    return 0


if __name__ == "__main__":
    sys.exit(main())