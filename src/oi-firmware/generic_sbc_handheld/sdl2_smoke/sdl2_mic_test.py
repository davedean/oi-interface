#!/usr/bin/env python3
"""SDL2 audio capture test for RG351P USB mic.

Records 3 seconds of audio from the USB mic via SDL2 capture device.
Saves raw PCM16 to /storage/roms/ports/OiSmokeTest/mic_test.raw
"""

from __future__ import annotations

import ctypes
import os
import sys
import time

os.environ.setdefault("PYSDL2_DLL_PATH", "/usr/lib")

try:
    import sdl2
except ImportError:
    pm_exlibs = "/storage/roms/ports/PortMaster/exlibs"
    if os.path.isdir(pm_exlibs) and pm_exlibs not in sys.path:
        sys.path.insert(0, pm_exlibs)
    import sdl2

from sdl2 import (
    SDL_INIT_AUDIO, SDL_AUDIO_ALLOW_FORMAT_CHANGE,
    SDL_OpenAudioDevice, SDL_CloseAudioDevice,
    SDL_PauseAudioDevice,
    SDL_AudioSpec,
    SDL_QuitSubSystem, SDL_Quit, SDL_Init,
    SDL_GetError,
)
from sdl2.audio import SDL_DequeueAudio


def main():
    out_path = "/storage/roms/ports/OiSmokeTest/mic_test.raw"
    SAMPLE_RATE = 16000
    DURATION_S = 3

    if SDL_Init(SDL_INIT_AUDIO) != 0:
        print(f"SDL_Init failed: {SDL_GetError()}")
        return 1

    # List capture devices
    num = sdl2.SDL_GetNumAudioDevices(1)
    print(f"Capture devices: {num}")
    for i in range(num):
        name = sdl2.SDL_GetAudioDeviceName(i, 1)
        print(f"  [{i}] {name}")

    # Open capture (default device, or pass specific name)
    desired = SDL_AudioSpec(freq=SAMPLE_RATE, aformat=sdl2.AUDIO_S16LSB, channels=1, samples=1024)
    obtained = SDL_AudioSpec(freq=0, aformat=0, channels=0, samples=0)

    dev_name = b"USB PnP Sound Device, USB Audio"  # explicitly select USB mic
    dev_id = SDL_OpenAudioDevice(
        dev_name,
        1,     # iscapture
        desired,
        obtained,
        SDL_AUDIO_ALLOW_FORMAT_CHANGE,
    )
    if dev_id == 0:
        print(f"OpenAudioDevice failed: {SDL_GetError()}")
        SDL_QuitSubSystem(SDL_INIT_AUDIO)
        SDL_Quit()
        return 1

    print(f"Opened capture device id={dev_id}")
    print(f"Obtained: {obtained.freq}Hz {obtained.channels}ch format={obtained.format} samples={obtained.samples}")

    # Start capturing
    SDL_PauseAudioDevice(dev_id, 0)

    buffer = bytearray()
    start = time.time()
    chunk_size = obtained.samples * obtained.channels * 2  # 2 bytes per S16 sample

    print(f"Recording {DURATION_S}s...")
    while time.time() - start < DURATION_S:
        chunk = bytearray(chunk_size)
        c_chunk = (ctypes.c_ubyte * chunk_size).from_buffer(chunk)
        received = SDL_DequeueAudio(dev_id, c_chunk, chunk_size)
        if received > 0:
            buffer.extend(chunk[:received])
        else:
            time.sleep(0.01)

    # Stop
    SDL_PauseAudioDevice(dev_id, 1)
    SDL_CloseAudioDevice(dev_id)
    SDL_QuitSubSystem(SDL_INIT_AUDIO)
    SDL_Quit()

    with open(out_path, "wb") as fh:
        fh.write(buffer)

    print(f"Recorded {len(buffer)} bytes ({len(buffer)//2} samples, {len(buffer)/(2*SAMPLE_RATE):.2f}s)")
    print(f"Saved to: {out_path}")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
