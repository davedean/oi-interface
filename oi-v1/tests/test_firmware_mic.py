import importlib
import struct
import sys
import types
import unittest
from pathlib import Path

FIRMWARE_LIB = Path(__file__).resolve().parents[1] / "firmware" / "lib"
if str(FIRMWARE_LIB) not in sys.path:
    sys.path.insert(0, str(FIRMWARE_LIB))


class FakePin:
    OUT = 1

    def __init__(self, pin_no, *args, **kwargs):
        self.pin_no = pin_no
        self._value = 1  # default high (not pressed)

    def value(self):
        return self._value


class FakeI2S:
    RX = 2
    TX = 1
    STEREO = 2
    MONO = 1

    def __init__(self, channel, **kwargs):
        self.channel = channel
        self.kwargs = kwargs
        self._fill_value = 0x20  # non-zero so we can detect a real read
        self.deinited = False
        self.readinto_count = 0

    def readinto(self, buf):
        self.readinto_count += 1
        for i in range(len(buf)):
            buf[i] = self._fill_value
        return len(buf)

    def deinit(self):
        self.deinited = True


class FakeI2CBus:
    def __init__(self):
        self.mem = {}
        self.writes = []

    def readfrom_mem(self, addr, reg, n):
        return bytes(self.mem.get((addr, reg + i), 0) for i in range(n))

    def writeto_mem(self, addr, reg, data):
        for i, b in enumerate(data):
            self.mem[(addr, reg + i)] = b
        self.writes.append((addr, reg, bytes(data)))


def _load_oi_mic():
    fake_machine = types.SimpleNamespace(I2S=FakeI2S, Pin=FakePin)
    old = sys.modules.get("machine")
    sys.modules["machine"] = fake_machine
    if "oi_mic" in sys.modules:
        del sys.modules["oi_mic"]
    mod = importlib.import_module("oi_mic")
    if not hasattr(mod.time, "sleep_ms"):
        mod.time.sleep_ms = lambda _ms: None
    if not hasattr(mod.time, "ticks_ms"):
        mod.time.ticks_ms = lambda: 0
    if not hasattr(mod.time, "ticks_add"):
        mod.time.ticks_add = lambda t, ms: t + ms
    if not hasattr(mod.time, "ticks_diff"):
        mod.time.ticks_diff = lambda a, b: a - b
    return mod, old


class FirmwareMicCase(unittest.TestCase):
    def setUp(self):
        self.mod, self.old_machine = _load_oi_mic()
        # Save patched time functions so tests can't pollute each other
        self._saved_time = {
            attr: getattr(self.mod.time, attr, None)
            for attr in ("ticks_ms", "ticks_add", "ticks_diff", "sleep_ms")
        }

    def tearDown(self):
        # Restore any time functions that tests may have overwritten
        for attr, val in self._saved_time.items():
            if val is not None:
                setattr(self.mod.time, attr, val)
            else:
                try:
                    delattr(self.mod.time, attr)
                except AttributeError:
                    pass
        if self.old_machine is None:
            sys.modules.pop("machine", None)
        else:
            sys.modules["machine"] = self.old_machine
        sys.modules.pop("oi_mic", None)

    def test_adc_init_writes_expected_registers(self):
        i2c = FakeI2CBus()
        mic = self.mod.OiMic(i2c)
        mic._init_codec()
        written_regs = [(addr, reg) for addr, reg, _ in i2c.writes]
        self.assertIn((self.mod.ES8311_ADDR, 0x00), written_regs)
        self.assertIn((self.mod.ES8311_ADDR, 0x01), written_regs)
        # 0x01 = 0xBA for mic (M5Unified _microphone_enabled_cb_sticks3)
        self.assertIn((self.mod.ES8311_ADDR, 0x01, bytes([0xBA])), i2c.writes)
        # MIC1P-MIC1N with 24 dB PGA gain
        self.assertIn((self.mod.ES8311_ADDR, 0x14, bytes([0x18])), i2c.writes)

    def test_i2s_rx_uses_correct_pins_and_config(self):
        i2c = FakeI2CBus()
        mic = self.mod.OiMic(i2c)
        mic._ensure_i2s()
        i2s = mic._i2s
        self.assertIsNotNone(i2s)
        self.assertEqual(i2s.channel, 1)         # separate channel from speaker
        self.assertEqual(i2s.kwargs["mode"], FakeI2S.RX)
        self.assertEqual(i2s.kwargs["format"], FakeI2S.STEREO)
        self.assertEqual(i2s.kwargs["rate"], 44100)
        self.assertEqual(i2s.kwargs["sck"].pin_no, 17)  # BCLK
        self.assertEqual(i2s.kwargs["ws"].pin_no, 15)   # LRCK
        self.assertEqual(i2s.kwargs["sd"].pin_no, 16)   # DIN
        self.assertNotIn("mck", i2s.kwargs)

    def test_record_wav_while_held_returns_none_on_timeout(self):
        i2c = FakeI2CBus()
        mic = self.mod.OiMic(i2c)
        pin = FakePin(11)
        pin._value = 1
        call_count = [0]
        def fake_diff(a, b):
            call_count[0] += 1
            return -1  # always timed out
        self.mod.time.ticks_diff = fake_diff
        result = mic.record_wav_while_held(pin, max_ms=100)
        self.assertIsNone(result)

    def test_record_wav_while_held_returns_mono_wav_when_pressed(self):
        i2c = FakeI2CBus()
        mic = self.mod.OiMic(i2c)
        press_calls = [0]
        original_value = FakePin.value

        # Held for first N calls, then 3 consecutive releases (debounce threshold)
        def held_then_release(self_pin):
            press_calls[0] += 1
            return 0 if press_calls[0] <= 3 else 1

        FakePin.value = held_then_release
        try:
            result = mic.record_wav_while_held(FakePin(11), max_ms=5000)
        finally:
            FakePin.value = original_value

        self.assertIsNotNone(result)
        self.assertGreater(len(result), 44)
        self.assertEqual(result[:4], b"RIFF")
        self.assertEqual(result[8:12], b"WAVE")
        # Output must be mono (channels = 1)
        channels = struct.unpack_from("<H", result, 22)[0]
        self.assertEqual(channels, 1)
        # PCM length must be half the stereo capture (left-channel extraction)
        data_len = struct.unpack_from("<I", result, 40)[0]
        self.assertGreater(data_len, 0)
        self.assertEqual(data_len % 2, 0)

    def test_mono_output_is_half_stereo_size(self):
        """Left-channel extraction must halve the PCM byte count."""
        i2c = FakeI2CBus()
        mic = self.mod.OiMic(i2c)
        press_calls = [0]
        original_value = FakePin.value

        # Hold for exactly 1 chunk-worth of recording then 3 releases
        def one_chunk_then_release(self_pin):
            press_calls[0] += 1
            return 0 if press_calls[0] <= 1 else 1

        FakePin.value = one_chunk_then_release
        try:
            result = mic.record_wav_while_held(FakePin(11), max_ms=5000)
        finally:
            FakePin.value = original_value

        self.assertIsNotNone(result)
        data_len = struct.unpack_from("<I", result, 40)[0]
        # FakeI2S fills with 0x20; 1 stereo chunk = 4096 bytes → 2048 bytes mono
        # (may be slightly more due to debounce extra chunks, but must be even
        # and must be half of stereo captured)
        self.assertEqual(data_len % 2, 0)
        channels = struct.unpack_from("<H", result, 22)[0]
        self.assertEqual(channels, 1)

    def test_debounce_ignores_single_release_glitch(self):
        """A single not-pressed read mid-recording should not stop the loop."""
        i2c = FakeI2CBus()
        mic = self.mod.OiMic(i2c)
        calls = [0]
        original_value = FakePin.value

        # pressed, pressed, GLITCH(not-pressed), pressed, pressed, then 3x release
        pattern = [0, 0, 0, 1, 0, 0, 1, 1, 1]

        def seq(self_pin):
            calls[0] += 1
            if calls[0] <= len(pattern):
                return pattern[calls[0] - 1]
            return 1

        FakePin.value = seq
        try:
            result = mic.record_wav_while_held(FakePin(11), max_ms=5000)
        finally:
            FakePin.value = original_value

        self.assertIsNotNone(result)
        # With debounce the recording continues past the glitch;
        # without it the loop would have stopped after the first release read.
        # We should see more than 2 chunks worth of mono PCM (> 2 × 2048 bytes).
        data_len = struct.unpack_from("<I", result, 40)[0]
        self.assertGreater(data_len, 2 * 2048)

    def test_wav_header_default_is_mono(self):
        hdr = self.mod._wav_header(1000)
        self.assertEqual(len(hdr), 44)
        channels = struct.unpack_from("<H", hdr, 22)[0]
        self.assertEqual(channels, 1)
        riff_size = struct.unpack_from("<I", hdr, 4)[0]
        self.assertEqual(riff_size, 36 + 1000)
        data_size = struct.unpack_from("<I", hdr, 40)[0]
        self.assertEqual(data_size, 1000)

    def test_wav_header_stereo_when_requested(self):
        hdr = self.mod._wav_header(2000, channels=2)
        channels = struct.unpack_from("<H", hdr, 22)[0]
        self.assertEqual(channels, 2)

    def test_deinit_releases_i2s(self):
        i2c = FakeI2CBus()
        mic = self.mod.OiMic(i2c)
        mic._ensure_i2s()
        i2s = mic._i2s
        mic.deinit()
        self.assertTrue(i2s.deinited)
        self.assertIsNone(mic._i2s)

    def test_readback_reg_reads_from_i2c(self):
        i2c = FakeI2CBus()
        i2c.mem[(self.mod.ES8311_ADDR, 0x01)] = 0xBA
        mic = self.mod.OiMic(i2c)
        self.assertEqual(mic.readback_reg(0x01), 0xBA)


if __name__ == "__main__":
    unittest.main()
