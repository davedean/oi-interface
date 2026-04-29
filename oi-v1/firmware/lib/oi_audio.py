# oi_audio.py — I2S TX + ES8311 DAC + AW8737 amp on M5StickS3
# Source: M5Unified _speaker_enabled_cb_sticks3 + M5Stack official docs
# NOTE: ES8311 register sequence is 1-source (M5Unified). Treat as provisional.

import math, struct, time
from machine import I2S, Pin

# I2S pin assignments (M5StickS3 hardware — see HARDWARE.md)
_BCLK = 17
_LRCK = 15
_DOUT = 14
_MCLK = 18

ES8311_ADDR  = 0x18
# ES8311 speaker/DAC init — verified against M5Unified
# `_speaker_enabled_cb_sticks3` (M5Unified.cpp lines 454–488). The codec
# locks its PLL to BCLK (0x01=0xB5), so MCLK on Pin 18 is harmless but
# unused by the clock manager. MULT_PRE=3 is sized for BCLK at 44.1 kHz
# stereo 16-bit (= 1.4112 MHz). At lower rates BCLK drops below the PLL's
# usable range and the DAC stays silent — _SAMPLE_RATE must stay at 44100.
_DAC_INIT = (
    (0x00, 0x80),  # Reset / CSM power on
    (0x01, 0xB5),  # Clock manager: lock to BCLK (M5Unified value)
    (0x02, 0x18),  # Clock pre-divider: MULT_PRE = 3
    (0x0D, 0x01),  # System: power up analog
    (0x12, 0x00),  # System: power up DAC
    (0x13, 0x10),  # System: enable HP drive output
    (0x32, 0xBF),  # DAC: volume = 0 dB unity
    (0x37, 0x08),  # DAC: bypass EQ
)

_SAMPLE_RATE = 44100


class OiAudio:
    """ES8311 DAC + AW8737 amp speaker output for M5StickS3."""

    def __init__(self, i2c, pmic=None):
        self._i2c          = i2c
        self._pmic         = pmic
        self._i2s          = None
        self._initialised  = False
        self._muted        = False
        self._volume_pct   = 100

    def _write_dac_volume(self):
        """Write current volume to ES8311 register 0x32 (DAC digital volume)."""
        if not self._initialised:
            return
        # 0xBF = unity gain (100%); linear scale down to 0 = muted
        val = 0 if self._muted else int(0xBF * self._volume_pct // 100)
        self._i2c.writeto_mem(ES8311_ADDR, 0x32, bytes([val]))

    def _init_codec(self):
        for reg, val in _DAC_INIT:
            self._i2c.writeto_mem(ES8311_ADDR, reg, bytes([val]))
            time.sleep_ms(2)
        self._initialised = True
        self._write_dac_volume()  # apply current volume setting over the 0xBF default

    def _set_amp(self, on):
        if self._pmic is not None:
            self._pmic.enable_speaker_amp(on)

    def set_muted(self, muted):
        self._muted = bool(muted)
        self._write_dac_volume()
        if self._initialised:
            self._set_amp(not self._muted)

    def is_muted(self):
        return self._muted

    def set_volume(self, pct):
        self._volume_pct = max(0, min(100, int(pct)))
        self.set_muted(self._volume_pct == 0)

    def volume(self):
        return self._volume_pct

    def _ensure_i2s(self):
        if self._i2s is None:
            # Note: no mck= kwarg. MicroPython 1.28's ESP32-S3 I2S build
            # rejects it (TypeError: extra keyword arguments given). The
            # ES8311 is configured with reg 0x01=0xB5 to lock its PLL to
            # BCLK, so an unconnected MCLK is fine.
            self._i2s = I2S(
                0,
                sck=Pin(_BCLK),
                ws=Pin(_LRCK),
                sd=Pin(_DOUT),
                mode=I2S.TX,
                bits=16,
                format=I2S.STEREO,
                rate=_SAMPLE_RATE,
                ibuf=8192,
            )

    def _tone_buf(self, freq_hz, ms=80, rate=_SAMPLE_RATE, amplitude=8000):
        """Generate a stereo 16-bit little-endian sine tone.
        Volume is applied via the ES8311 DAC register, not here."""
        n = rate * ms // 1000
        buf = bytearray(n * 4)
        for i in range(n):
            v = int(amplitude * math.sin(2 * math.pi * freq_hz * i / rate))
            # Duplicate mono sample into L/R channels; ES8311 DAC path expects
            # normal stereo I2S frames even though the board speaker is mono.
            struct.pack_into('<hh', buf, i * 4, v, v)
        return buf

    def reset(self):
        """Mark codec as uninitialised (call when another driver has reset the codec)."""
        self._initialised = False
        if self._i2s is not None:
            try:
                self._i2s.deinit()
            except Exception:
                pass
            self._i2s = None

    def play_wav(self, wav_bytes):
        """Play a 44100 Hz stereo 16-bit WAV through the speaker.

        Returns 'ok', 'muted', or 'ERR: <msg>'.
        """
        if self._muted:
            return "muted"
        # Parse RIFF header, find fmt and data chunks
        if len(wav_bytes) < 12 or wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
            return "ERR: not a WAV"
        offset = 12
        n_channels = None
        data_offset = None
        data_size = None
        while offset + 8 <= len(wav_bytes):
            chunk_id = wav_bytes[offset:offset + 4]
            chunk_size = struct.unpack_from("<I", wav_bytes, offset + 4)[0]
            if chunk_id == b"fmt ":
                if chunk_size >= 16:
                    n_channels = struct.unpack_from("<H", wav_bytes, offset + 10)[0]
            elif chunk_id == b"data":
                data_offset = offset + 8
                data_size = chunk_size
                break
            offset += 8 + chunk_size
        if data_offset is None or data_size is None:
            return "ERR: no data chunk"
        if n_channels is None:
            return "ERR: no fmt chunk"
        if n_channels != 2:
            return "ERR: unsupported channels"
        if not self._initialised:
            try:
                self._init_codec()
            except Exception as e:
                return "ERR: codec " + repr(e)
        pcm = memoryview(wav_bytes)[data_offset:data_offset + data_size]
        try:
            self._ensure_i2s()
            self._set_amp(True)
            self._i2s.write(pcm)
            time.sleep_ms(80)
            return "ok"
        except Exception as e:
            return "ERR: " + repr(e)
        finally:
            self._set_amp(False)

    def chirp(self, kind="good"):
        """Play a two-tone major-third chirp. Returns 'ok' or 'ERR: <msg>'.

        kind: 'good'=ascending, 'bad'=descending.
        """
        if self._muted:
            return "muted"
        if not self._initialised:
            try:
                self._init_codec()
            except Exception as e:
                print("[oi_audio] codec init failed:", e)
                return "ERR: codec " + repr(e)
        try:
            self._ensure_i2s()
            self._set_amp(True)
            # C7/E7 picked for a quick "coin pickup" feel — short, bright,
            # cuts through ambient noise without being a long "boop".
            if kind == "bad":
                tones = (2637, 2093)  # E7 → C7 descending
            else:
                tones = (2093, 2637)  # C7 → E7 ascending
            for f in tones:
                self._i2s.write(self._tone_buf(f))
            # Keep the amp enabled briefly so the tail of the DMA buffer is not
            # clipped by immediately dropping AW8737 enable.
            time.sleep_ms(80)
            return "ok"
        except Exception as e:
            print("[oi_audio] chirp error:", e)
            return "ERR: " + repr(e)
        finally:
            self._set_amp(False)
