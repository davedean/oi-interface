import sys
import unittest
from pathlib import Path


FIRMWARE_LIB = Path(__file__).resolve().parents[1] / "firmware" / "lib"
if str(FIRMWARE_LIB) not in sys.path:
    sys.path.insert(0, str(FIRMWARE_LIB))


import oi_interaction as ui


class FakePin:
    def __init__(self, value=1):
        self._value = value

    def value(self):
        return self._value

    def set(self, value):
        self._value = value


class FakeClock:
    def __init__(self, now=0, wrap=None):
        self.now = now
        self.wrap = wrap

    def ticks_ms(self):
        return self.now

    def ticks_diff(self, a, b):
        if self.wrap is None:
            return a - b
        half = self.wrap // 2
        return ((a - b + half) % self.wrap) - half

    def advance(self, ms):
        self.now += ms
        if self.wrap is not None:
            self.now %= self.wrap


class GestureDetectorCase(unittest.TestCase):
    def make_detector(self, pin=None, clock=None):
        return ui.GestureDetector(pin or FakePin(), clock=clock or FakeClock())

    def settle(self, detector, pin, clock, value):
        pin.set(value)
        detector.poll()
        clock.advance(ui.DEFAULT_DEBOUNCE_MS)
        return detector.poll()

    def test_single_emits_after_double_window(self):
        pin = FakePin()
        clock = FakeClock()
        detector = self.make_detector(pin, clock)

        self.assertIsNone(self.settle(detector, pin, clock, 0))
        self.assertIsNone(self.settle(detector, pin, clock, 1))
        clock.advance(ui.DEFAULT_DOUBLE_MS - 1)
        self.assertIsNone(detector.poll())
        clock.advance(1)
        self.assertEqual(ui.GESTURE_SINGLE, detector.poll())

    def test_double_suppresses_single(self):
        pin = FakePin()
        clock = FakeClock()
        detector = self.make_detector(pin, clock)

        self.settle(detector, pin, clock, 0)
        self.settle(detector, pin, clock, 1)
        clock.advance(ui.DEFAULT_DOUBLE_MS // 2)
        self.assertEqual(ui.GESTURE_DOUBLE, self.settle(detector, pin, clock, 0))
        self.assertIsNone(self.settle(detector, pin, clock, 1))
        clock.advance(ui.DEFAULT_DOUBLE_MS)
        self.assertIsNone(detector.poll())

    def test_long_emits_on_release_after_threshold(self):
        pin = FakePin()
        clock = FakeClock()
        detector = self.make_detector(pin, clock)

        self.settle(detector, pin, clock, 0)
        clock.advance(ui.DEFAULT_LONG_MS)
        self.assertIsNone(detector.poll())
        self.assertEqual(ui.GESTURE_LONG, self.settle(detector, pin, clock, 1))
        clock.advance(ui.DEFAULT_DOUBLE_MS)
        self.assertIsNone(detector.poll())

    def test_bounce_does_not_create_press_or_double(self):
        pin = FakePin()
        clock = FakeClock()
        detector = self.make_detector(pin, clock)

        pin.set(0)
        detector.poll()
        clock.advance(ui.DEFAULT_DEBOUNCE_MS - 1)
        self.assertIsNone(detector.poll())
        pin.set(1)
        detector.poll()
        clock.advance(ui.DEFAULT_DEBOUNCE_MS)
        self.assertIsNone(detector.poll())
        clock.advance(ui.DEFAULT_DOUBLE_MS)
        self.assertIsNone(detector.poll())

    def test_constructed_while_held_ignores_until_release(self):
        pin = FakePin(0)
        clock = FakeClock()
        detector = self.make_detector(pin, clock)

        clock.advance(ui.DEFAULT_LONG_MS + ui.DEFAULT_DEBOUNCE_MS)
        self.assertIsNone(detector.poll())
        self.assertIsNone(self.settle(detector, pin, clock, 1))

        self.settle(detector, pin, clock, 0)
        self.settle(detector, pin, clock, 1)
        clock.advance(ui.DEFAULT_DOUBLE_MS)
        self.assertEqual(ui.GESTURE_SINGLE, detector.poll())

    def test_ticks_wraparound(self):
        pin = FakePin()
        clock = FakeClock(now=990, wrap=1000)
        detector = self.make_detector(pin, clock)

        self.settle(detector, pin, clock, 0)
        self.settle(detector, pin, clock, 1)
        clock.advance(ui.DEFAULT_DOUBLE_MS)
        self.assertEqual(ui.GESTURE_SINGLE, detector.poll())


class DebouncedPressCase(unittest.TestCase):
    def test_wake_press_fires_once_on_debounced_falling_edge(self):
        pin = FakePin()
        clock = FakeClock()
        wake = ui.DebouncedPress(pin, clock=clock)

        pin.set(0)
        self.assertFalse(wake.pressed())
        clock.advance(ui.DEFAULT_DEBOUNCE_MS - 1)
        self.assertFalse(wake.pressed())
        clock.advance(1)
        self.assertTrue(wake.pressed())
        self.assertFalse(wake.pressed())
        pin.set(1); wake.pressed(); clock.advance(ui.DEFAULT_DEBOUNCE_MS)
        self.assertFalse(wake.pressed())

    def test_constructed_while_held_does_not_fire_until_fresh_press(self):
        pin = FakePin(0)
        clock = FakeClock()
        wake = ui.DebouncedPress(pin, clock=clock)

        clock.advance(ui.DEFAULT_DEBOUNCE_MS)
        self.assertFalse(wake.pressed())
        pin.set(1); wake.pressed(); clock.advance(ui.DEFAULT_DEBOUNCE_MS); self.assertFalse(wake.pressed())
        pin.set(0); wake.pressed(); clock.advance(ui.DEFAULT_DEBOUNCE_MS); self.assertTrue(wake.pressed())


class ActionMappingCase(unittest.TestCase):
    def test_idle_mapping(self):
        # A.tap / A.double → ping; B.long → settings; A.long is now unmapped
        self.assertEqual(ui.ACTION_PING, ui.action_for(ui.MODE_IDLE, ui.BTN_A, ui.GESTURE_SINGLE))
        self.assertEqual(ui.ACTION_PING, ui.action_for(ui.MODE_IDLE, ui.BTN_A, ui.GESTURE_DOUBLE))
        self.assertEqual(ui.ACTION_OPEN_SETTINGS, ui.action_for(ui.MODE_IDLE, ui.BTN_B, ui.GESTURE_LONG))
        self.assertEqual(ui.ACTION_NONE, ui.action_for(ui.MODE_IDLE, ui.BTN_A, ui.GESTURE_LONG))
        self.assertEqual(ui.ACTION_NONE, ui.action_for(ui.MODE_IDLE, ui.BTN_B, ui.GESTURE_SINGLE))

    def test_session_mapping(self):
        self.assertEqual(ui.ACTION_OPEN_MENU, ui.action_for(ui.MODE_SESSION, ui.BTN_A, ui.GESTURE_SINGLE))
        self.assertEqual(ui.ACTION_SPEAK, ui.action_for(ui.MODE_SESSION, ui.BTN_A, ui.GESTURE_DOUBLE))
        self.assertEqual(ui.ACTION_NEXT_SESSION, ui.action_for(ui.MODE_SESSION, ui.BTN_B, ui.GESTURE_SINGLE))
        self.assertEqual(ui.ACTION_OPEN_SETTINGS, ui.action_for(ui.MODE_SESSION, ui.BTN_B, ui.GESTURE_LONG))
        self.assertEqual(ui.ACTION_NONE, ui.action_for(ui.MODE_SESSION, ui.BTN_A, ui.GESTURE_LONG))

    def test_question_mapping(self):
        # A.long is now unmapped in question mode; settings via B.long
        self.assertEqual(ui.ACTION_ANSWER, ui.action_for(ui.MODE_QUESTION, ui.BTN_A, ui.GESTURE_SINGLE))
        self.assertEqual(ui.ACTION_NONE, ui.action_for(ui.MODE_QUESTION, ui.BTN_A, ui.GESTURE_LONG))
        self.assertEqual(ui.ACTION_NEXT, ui.action_for(ui.MODE_QUESTION, ui.BTN_B, ui.GESTURE_SINGLE))
        self.assertEqual(ui.ACTION_OPEN_SETTINGS, ui.action_for(ui.MODE_QUESTION, ui.BTN_B, ui.GESTURE_LONG))
        self.assertEqual(ui.ACTION_NONE, ui.action_for(ui.MODE_QUESTION, ui.BTN_B, ui.GESTURE_DOUBLE))

    def test_settings_mapping(self):
        self.assertEqual(ui.ACTION_EDIT, ui.action_for(ui.MODE_SETTINGS, ui.BTN_A, ui.GESTURE_SINGLE))
        self.assertEqual(ui.ACTION_NONE, ui.action_for(ui.MODE_SETTINGS, ui.BTN_A, ui.GESTURE_LONG))
        self.assertEqual(ui.ACTION_NEXT, ui.action_for(ui.MODE_SETTINGS, ui.BTN_B, ui.GESTURE_SINGLE))
        self.assertEqual(ui.ACTION_SAVE_EXIT, ui.action_for(ui.MODE_SETTINGS, ui.BTN_B, ui.GESTURE_LONG))


if __name__ == "__main__":
    unittest.main()
