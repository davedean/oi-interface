"""Device state machine matching the firmware spec (§5.1)."""
from __future__ import annotations

from enum import Enum

# ------------------------------------------------------------------
# State definitions
# ------------------------------------------------------------------

class State(str, Enum):
    """All valid device states."""

    BOOTING = "BOOTING"
    PAIRING = "PAIRING"
    READY = "READY"
    RECORDING = "RECORDING"
    UPLOADING = "UPLOADING"
    THINKING = "THINKING"
    RESPONSE_CACHED = "RESPONSE_CACHED"
    PLAYING = "PLAYING"
    MUTED = "MUTED"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"
    SAFE_MODE = "SAFE_MODE"


# ------------------------------------------------------------------
# Transition table
# ------------------------------------------------------------------

# Map: from_state → set of valid destination states.
_TRANSITIONS: dict[State, frozenset[State]] = {
    State.BOOTING:      frozenset({State.PAIRING, State.READY, State.OFFLINE}),
    State.PAIRING:      frozenset({State.READY, State.ERROR}),
    State.READY:        frozenset({State.RECORDING, State.THINKING, State.MUTED, State.OFFLINE, State.BOOTING}),
    State.RECORDING:    frozenset({State.UPLOADING, State.READY}),
    State.UPLOADING:    frozenset({State.THINKING}),
    State.THINKING:     frozenset({State.RESPONSE_CACHED, State.READY, State.ERROR}),
    State.RESPONSE_CACHED: frozenset({State.PLAYING, State.READY, State.THINKING}),
    State.PLAYING:      frozenset({State.RESPONSE_CACHED, State.READY}),
    State.MUTED:        frozenset({State.READY, State.OFFLINE}),
    State.OFFLINE:      frozenset({State.READY, State.ERROR}),
    State.ERROR:        frozenset({State.SAFE_MODE, State.READY}),
    State.SAFE_MODE:    frozenset({State.BOOTING}),
}

# Any state can transition to ERROR, SAFE_MODE, or BOOTING (for reboot/shutdown).
_ANY_STATE = frozenset({State.ERROR, State.SAFE_MODE, State.BOOTING})


def _valid_destinations(from_state: State) -> frozenset[State]:
    base = _TRANSITIONS.get(from_state, frozenset())
    return base | _ANY_STATE


# ------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------

class InvalidTransition(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, from_state: State, to_state: State) -> None:
        super().__init__(f"Invalid transition: {from_state.value} → {to_state.value}")
        self.from_state = from_state
        self.to_state = to_state


# ------------------------------------------------------------------
# StateMachine
# ------------------------------------------------------------------

class StateMachine:
    """Deterministic state machine for a virtual device.

    Parameters
    ----------
    initial_state : State
        The starting state (default READY).
    """

    __slots__ = (
        "_state",
        "_display_state",
        "_display_label",
        "_muted_until",
        "_caching",
        "_cache_chunk_count",
        "_volume",
        "_led_enabled",
        "_brightness",
    )

    def __init__(self, initial_state: State = State.READY) -> None:
        self._state = initial_state
        self._display_state: str | None = None
        self._display_label: str | None = None
        self._muted_until: str | None = None
        self._caching = False
        self._cache_chunk_count = 0
        self._volume: int = 80  # default volume (0-100)
        self._led_enabled: bool = True
        self._brightness: int = 100  # default brightness (0-100)

    @property
    def state(self) -> State:
        """Current state."""
        return self._state

    def transition(self, new_state: State) -> State:
        """Validate and perform a transition.

        Raises
        ------
        InvalidTransition
            If the transition is not in the allowed set.
        """
        if new_state not in _valid_destinations(self._state):
            raise InvalidTransition(self._state, new_state)
        self._state = new_state
        return self._state

    def assert_state(self, expected: State) -> None:
        """Assert the current state matches ``expected``."""
        assert self._state == expected, (
            f"Expected state {expected.value!r}, got {self._state.value!r}"
        )

    def receive_command(self, op: str, args: dict | None = None) -> State:
        """Process a DATP command operator and return the implied state.

        This maps command operators to the state the device should advance to
        after acknowledging the command.

        Parameters
        ----------
        op : str
            The DATP command operator (e.g. 'display.show_status').
        args : dict, optional
            Command arguments (varies by op type).
        """
        if args is None:
            args = {}

        if op == "display.show_status":
            self._display_state = args.get("state")
            self._display_label = args.get("label")
            return self._state

        if op == "display.show_card":
            # A text/card response indicates the agent has completed thinking.
            # Move THINKING -> RESPONSE_CACHED when valid; otherwise keep current state.
            if State.RESPONSE_CACHED in _valid_destinations(self._state):
                return self.transition(State.RESPONSE_CACHED)
            return self._state

        if op == "audio.cache.put_begin":
            # Start caching sequence — stays in current state until put_end.
            # Accepted from UPLOADING (device is uploading, agent responded before thinking event)
            # or from THINKING (standard flow after agent response).
            self._caching = True
            self._cache_chunk_count = 0
            return self._state

        if op == "audio.cache.put_chunk":
            # Intermediate chunk in cache sequence.
            if self._caching:
                self._cache_chunk_count += 1
            return self._state

        if op == "audio.cache.put_end":
            # Complete cache sequence — transition to RESPONSE_CACHED.
            # Accepted from any state that allows this transition (UPLOADING, THINKING, etc.).
            # States that cannot transition to RESPONSE_CACHED are accepted silently
            # (the caching flag is still cleared to keep internal state clean).
            self._caching = False
            if State.RESPONSE_CACHED in _valid_destinations(self._state):
                return self.transition(State.RESPONSE_CACHED)
            return self._state

        if op == "audio.play":
            # Idempotent: if already PLAYING, treat as a no-op rather than raising.
            if self._state == State.PLAYING:
                return self._state
            return self.transition(State.PLAYING)

        if op == "audio.stop":
            # Idempotent: if already READY, no-op.
            if self._state == State.READY:
                return self._state
            return self.transition(State.READY)

        if op == "device.mute_until":
            self._muted_until = args.get("until")
            return self.transition(State.MUTED)

        if op == "device.set_brightness":
            # No state change; brightness is a property.
            self._brightness = args.get("value", self._brightness)
            return self._state

        if op == "device.set_volume":
            # No state change; volume is a property.
            self._volume = args.get("level", self._volume)
            return self._state

        if op == "device.set_led":
            # No state change; LED is a property.
            self._led_enabled = args.get("enabled", self._led_enabled)
            return self._state

        if op == "device.reboot":
            # Reboot transitions to BOOTING (system reset)
            return self.transition(State.BOOTING)

        if op == "device.shutdown":
            # Shutdown transitions to OFFLINE (device powered off)
            return self.transition(State.OFFLINE)

        if op == "storage.format":
            # Format clears audio cache - no state change but could affect cached audio
            # This is a no-op for state machine but the device would respond
            return self._state

        if op == "wifi.configure":
            # WiFi configuration doesn't change device state
            return self._state

        # Unknown op — silent no-op (future extensibility).
        return self._state

    # ------------------------------------------------------------------
    # Property accessors
    # ------------------------------------------------------------------

    @property
    def volume(self) -> int:
        """Current volume level (0-100)."""
        return self._volume

    @property
    def led_enabled(self) -> bool:
        """Whether LED is enabled."""
        return self._led_enabled

    @property
    def brightness(self) -> int:
        """Current brightness level (0-100)."""
        return self._brightness
