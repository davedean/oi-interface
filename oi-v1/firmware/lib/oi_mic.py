# oi_mic.py — ES8311 ADC + I2S RX mic capture on M5StickS3
# Source: M5Unified _microphone_enabled_cb_sticks3 (register sequence)
# HARDWARE.md pins: BCLK=G17, LRCK=G15, DIN=G16 (corrected 2026-04-25)
# NOTE: Codec chip reset (reg 0x00) destroys DAC config — call audio.reset()
#       before recording if OiAudio was previously active.

import struct
import time
from machine import I2S, Pin

ES8311_ADDR = 0x18

# ADC init — sourced from M5Unified _microphone_enabled_cb_sticks3.
# Includes chip reset (0x00=0x80) to ensure a clean ADC path; this clears any
# prior DAC config, which is acceptable for push-to-talk (not simultaneous).
# Clock stays at 44100 Hz stereo (BCLK = 1.4112 MHz) to stay above the ES8311
# PLL lower limit — the same constraint that broke the speaker at 16 kHz.
_ADC_INIT = (
    (0x00, 0x80),  # Chip reset / power on
    (0x01, 0xBA),  # Clock manager: BCLK as MCLK source (M5Unified mic value)
    (0x02, 0x18),  # Clock pre-divider: MULT_PRE = 3
    (0x0D, 0x01),  # System: power up analog
    (0x0E, 0x02),  # Enable PGA + ADC modulator
    (0x14, 0x18),  # MIC1P-MIC1N input, 24 dB PGA gain
    (0x17, 0xFF),  # ADC digital volume = max
    (0x1C, 0x6A),  # ADC EQ bypass + DC offset cancellation
)

_SAMPLE_RATE = 44100
_CHANNELS = 2      # I2S must be STEREO to keep BCLK = 1.4112 MHz above PLL limit
_BITS = 16
_IBUF = 8192
_CHUNK = 4096      # bytes per readinto(); ~23 ms per chunk at 44100 Hz stereo

# Require this many consecutive "not pressed" reads before ending recording.
# Guards against GPIO glitches from I2S DMA activity on nearby pins (15/16/17).
_RELEASE_DEBOUNCE = 3


def _wav_header(data_len, channels=1):
    """44-byte RIFF/WAV header for mono 44100 Hz 16-bit PCM by default."""
    byte_rate = _SAMPLE_RATE * channels * _BITS // 8
    block_align = channels * _BITS // 8
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_len, b"WAVE",
        b"fmt ", 16, 1, channels, _SAMPLE_RATE,
        byte_rate, block_align, _BITS,
        b"data", data_len,
    )


class OiMic:
    """ES8311 ADC + I2S RX audio capture for M5StickS3."""

    def __init__(self, i2c):
        self._i2c = i2c
        self._i2s = None

    def _init_codec(self):
        for reg, val in _ADC_INIT:
            self._i2c.writeto_mem(ES8311_ADDR, reg, bytes([val]))
            time.sleep_ms(2)

    def readback_reg(self, reg):
        """Read a single ES8311 register byte (diagnostic / verification)."""
        return self._i2c.readfrom_mem(ES8311_ADDR, reg, 1)[0]

    def _ensure_i2s(self):
        if self._i2s is None:
            # Channel 1 — channel 0 is reserved for OiAudio (speaker).
            # No mck= kwarg: MicroPython 1.28 ESP32-S3 I2S rejects it.
            self._i2s = I2S(
                1,
                sck=Pin(17),   # BCLK (shared with speaker)
                ws=Pin(15),    # LRCK (shared with speaker)
                sd=Pin(16),    # DIN — ESP32 receives from codec
                mode=I2S.RX,
                bits=_BITS,
                format=I2S.STEREO,
                rate=_SAMPLE_RATE,
                ibuf=_IBUF,
            )

    def record_wav_while_held(self, button_pin, max_ms=15000):
        """
        Record while button_pin is held low (active-low).
        Returns mono WAV bytes (RIFF header + PCM), or None if button not pressed.
        Caller should call audio.reset() beforehand if OiAudio was active.
        """
        # Wait up to 5s for initial press
        deadline = time.ticks_add(time.ticks_ms(), 5000)
        while button_pin.value() != 0:
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                return None
            time.sleep_ms(20)

        self._init_codec()
        time.sleep_ms(50)  # Allow ADC PLL and analog path to stabilize
        self._ensure_i2s()

        max_stereo = int(max_ms * _SAMPLE_RATE * _CHANNELS * _BITS // 8 // 1000)
        stereo_chunk = bytearray(_CHUNK)
        # Mono output buffer: half the stereo byte count
        max_mono = max_stereo // 2
        mono_buf = bytearray(max_mono)
        stereo_captured = 0
        mono_offset = 0
        rec_deadline = time.ticks_add(time.ticks_ms(), max_ms)
        release_count = 0

        while True:
            # Debounce: require _RELEASE_DEBOUNCE consecutive not-pressed reads
            # before treating as a real release (guards against I2S DMA glitches).
            if button_pin.value() != 0:
                release_count += 1
                if release_count >= _RELEASE_DEBOUNCE:
                    break
            else:
                release_count = 0
            if time.ticks_diff(rec_deadline, time.ticks_ms()) <= 0:
                break
            remaining = max_stereo - stereo_captured
            if remaining <= 0:
                break
            n = self._i2s.readinto(memoryview(stereo_chunk)[:min(_CHUNK, remaining)])
            if n > 0:
                stereo_captured += n
                # Extract left channel: stereo = [L_lo, L_hi, R_lo, R_hi, ...]
                src = 0
                dst = mono_offset
                for _ in range(n // 4):
                    mono_buf[dst] = stereo_chunk[src]
                    mono_buf[dst + 1] = stereo_chunk[src + 1]
                    dst += 2
                    src += 4
                mono_offset = dst

        if mono_offset == 0:
            return None

        pcm = bytes(mono_buf[:mono_offset])
        return bytes(_wav_header(len(pcm))) + pcm

    def deinit(self):
        """Release I2S resource so OiAudio can use the codec again."""
        if self._i2s is not None:
            try:
                self._i2s.deinit()
            except Exception:
                pass
            self._i2s = None
