# oi_interaction.py — testable button gestures and action mapping for oi.
#
# MicroPython-compatible: no dataclasses, no CPython-only imports required.

try:
    import time as _time
except Exception:  # pragma: no cover - defensive for unusual firmware builds
    _time = None


DEFAULT_DEBOUNCE_MS = 30
DEFAULT_LONG_MS = 800
DEFAULT_DOUBLE_MS = 400

BTN_A = "A"
BTN_B = "B"

GESTURE_SINGLE = "single"
GESTURE_DOUBLE = "double"
GESTURE_LONG = "long"

MODE_IDLE = "idle"
MODE_SESSION = "session"
MODE_QUESTION = "question"
MODE_SETTINGS = "settings"

ACTION_NONE = "none"
ACTION_PING = "ping"
ACTION_OPEN_SETTINGS = "open_settings"
ACTION_OPEN_MENU = "open_menu"
ACTION_NEXT = "next"
ACTION_NEXT_SESSION = "next_session"
ACTION_ANSWER = "answer"
ACTION_EDIT = "edit"
ACTION_SAVE_EXIT = "save_exit"
ACTION_VOICE = "voice"
ACTION_SPEAK = "speak"


class _DefaultClock:
    def ticks_ms(self):
        return _time.ticks_ms()

    def ticks_diff(self, a, b):
        return _time.ticks_diff(a, b)


class DebouncedPress:
    """
    Debounced falling-edge detector for active-low buttons.

    Constructing while the button is already held does not fire. The detector
    arms after it has observed a released/high state, so wake presses or object
    creation during a hold cannot leak into later actions.
    """

    def __init__(self, pin, debounce_ms=DEFAULT_DEBOUNCE_MS, clock=None):
        self._pin = pin
        self._debounce_ms = debounce_ms
        self._clock = clock or _DefaultClock()
        raw = pin.value()
        self._last_raw = raw
        self._stable = raw
        self._changed_at = self._clock.ticks_ms()
        self._armed = (raw != 0)

    def _diff(self, a, b):
        return self._clock.ticks_diff(a, b)

    def pressed(self):
        now = self._clock.ticks_ms()
        raw = self._pin.value()

        if raw != self._last_raw:
            self._last_raw = raw
            self._changed_at = now
            return False

        if raw != self._stable and self._diff(now, self._changed_at) >= self._debounce_ms:
            old = self._stable
            self._stable = raw
            if raw != 0:
                self._armed = True
                return False
            if old != 0 and self._armed:
                self._armed = False
                return True

        return False

    def raw_low(self):
        return self._pin.value() == 0


class GestureDetector:
    """
    Debounced active-low single/double/long press recognizer.

    Long presses preserve the original oi firmware semantics: the long gesture
    is emitted on release after the hold threshold, not immediately at the
    threshold. Double is emitted on the debounced second press, suppressing the
    pending single.
    """

    _IDLE = 0
    _PRESSED = 1
    _WAIT_2ND = 2
    _LONG_HELD = 3
    _IGNORE_UNTIL_RELEASE = 4
    _DOUBLE_HELD = 5

    def __init__(self, pin, debounce_ms=DEFAULT_DEBOUNCE_MS,
                 long_ms=DEFAULT_LONG_MS, double_ms=DEFAULT_DOUBLE_MS,
                 clock=None):
        self._pin = pin
        self._debounce_ms = debounce_ms
        self._long_ms = long_ms
        self._double_ms = double_ms
        self._clock = clock or _DefaultClock()
        raw = pin.value()
        self._last_raw = raw
        self._stable = raw
        self._changed_at = self._clock.ticks_ms()
        self._state = self._IGNORE_UNTIL_RELEASE if raw == 0 else self._IDLE
        self._t = self._changed_at

    def _diff(self, a, b):
        return self._clock.ticks_diff(a, b)

    def _stable_low(self):
        now = self._clock.ticks_ms()
        raw = self._pin.value()

        if raw != self._last_raw:
            self._last_raw = raw
            self._changed_at = now

        if raw != self._stable and self._diff(now, self._changed_at) >= self._debounce_ms:
            self._stable = raw

        return self._stable == 0

    def poll(self):
        now = self._clock.ticks_ms()
        low = self._stable_low()

        if self._state == self._IGNORE_UNTIL_RELEASE:
            if not low:
                self._state = self._IDLE
                self._t = now

        elif self._state == self._IDLE:
            if low:
                self._state = self._PRESSED
                self._t = now

        elif self._state == self._PRESSED:
            held = self._diff(now, self._t)
            if not low:
                if held < self._long_ms:
                    self._state = self._WAIT_2ND
                    self._t = now
                else:
                    self._state = self._IDLE
                    return GESTURE_LONG
            elif held >= self._long_ms:
                self._state = self._LONG_HELD

        elif self._state == self._LONG_HELD:
            if not low:
                self._state = self._IDLE
                return GESTURE_LONG

        elif self._state == self._WAIT_2ND:
            waited = self._diff(now, self._t)
            if low:
                self._state = self._DOUBLE_HELD
                return GESTURE_DOUBLE
            elif waited >= self._double_ms:
                self._state = self._IDLE
                return GESTURE_SINGLE

        elif self._state == self._DOUBLE_HELD:
            if not low:
                self._state = self._IDLE

        return None


_ACTIONS = {
    # Idle (no active session): A = ping, B.long = settings
    (MODE_IDLE, BTN_A, GESTURE_SINGLE): ACTION_PING,
    (MODE_IDLE, BTN_A, GESTURE_DOUBLE): ACTION_PING,
    (MODE_IDLE, BTN_B, GESTURE_LONG): ACTION_OPEN_SETTINGS,

    # Session idle: A.tap = command menu, A.double = ping, B.tap = next, B.long = settings
    (MODE_SESSION, BTN_A, GESTURE_SINGLE): ACTION_OPEN_MENU,
    (MODE_SESSION, BTN_A, GESTURE_DOUBLE): ACTION_SPEAK,
    (MODE_SESSION, BTN_B, GESTURE_SINGLE): ACTION_NEXT_SESSION,
    (MODE_SESSION, BTN_B, GESTURE_LONG): ACTION_OPEN_SETTINGS,

    # Question: A.tap = answer, B.tap = cycle options, B.long = settings
    (MODE_QUESTION, BTN_A, GESTURE_SINGLE): ACTION_ANSWER,
    (MODE_QUESTION, BTN_B, GESTURE_SINGLE): ACTION_NEXT,
    (MODE_QUESTION, BTN_B, GESTURE_LONG): ACTION_OPEN_SETTINGS,

    # Settings: A.tap = edit/cycle value, B.long = save + exit, B.tap = next item
    (MODE_SETTINGS, BTN_A, GESTURE_SINGLE): ACTION_EDIT,
    (MODE_SETTINGS, BTN_B, GESTURE_SINGLE): ACTION_NEXT,
    (MODE_SETTINGS, BTN_B, GESTURE_LONG): ACTION_SAVE_EXIT,
}


def action_for(mode, button, gesture):
    """Return the semantic action for a mode/button/gesture tuple."""
    return _ACTIONS.get((mode, button, gesture), ACTION_NONE)
