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

    _DISPLAY_DELTA_OPS = frozenset({"display.show_response_delta", "display.show_text_delta"})
    _STATELESS_COMMANDS = frozenset({"storage.format", "wifi.configure"})

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
        args = args or {}

        if op == "display.show_status":
            self._display_state = args.get("state")
            self._display_label = args.get("label")
            return self._state

        if op == "display.show_card":
            return self._transition_if_allowed(State.RESPONSE_CACHED)

        if op in self._DISPLAY_DELTA_OPS:
            if args.get("is_final", False):
                return self._transition_if_allowed(State.RESPONSE_CACHED)
            return self._state

        if op == "audio.cache.put_begin":
            self._caching = True
            self._cache_chunk_count = 0
            return self._state

        if op == "audio.cache.put_chunk":
            if self._caching:
                self._cache_chunk_count += 1
            return self._state

        if op == "audio.cache.put_end":
            self._caching = False
            return self._transition_if_allowed(State.RESPONSE_CACHED)

        if op == "audio.play":
            return self._state if self._state == State.PLAYING else self.transition(State.PLAYING)

        if op == "audio.stop":
            return self._state if self._state == State.READY else self.transition(State.READY)

        if op == "device.mute_until":
            self._muted_until = args.get("until")
            return self.transition(State.MUTED)

        if op == "device.set_brightness":
            return self._set_and_keep_state("_brightness", args.get("value", self._brightness))

        if op == "device.set_volume":
            return self._set_and_keep_state("_volume", args.get("level", self._volume))

        if op == "device.set_led":
            return self._set_and_keep_state("_led_enabled", args.get("enabled", self._led_enabled))

        if op == "device.reboot":
            return self.transition(State.BOOTING)

        if op == "device.shutdown":
            return self.transition(State.OFFLINE)

        if op in self._STATELESS_COMMANDS:
            return self._state

        return self._state

    def _transition_if_allowed(self, new_state: State) -> State:
        """Transition to ``new_state`` when valid; otherwise keep the current state."""
        if new_state in _valid_destinations(self._state):
            return self.transition(new_state)
        return self._state

    def _set_and_keep_state(self, attr_name: str, value: object) -> State:
        """Update a non-state property without changing the current state."""
        setattr(self, attr_name, value)
        return self._state

    # ------------------------------------------------------------------
    # Property accessors
    # ------------------------------------------------------------------

    @property
    def display_state(self) -> str | None:
        """Last display state set by display.show_status."""
        return self._display_state

    @property
    def display_label(self) -> str | None:
        """Last display label set by display.show_status."""
        return self._display_label

    @property
    def muted_until(self) -> str | None:
        """Mute-until timestamp from device.mute_until."""
        return self._muted_until

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
