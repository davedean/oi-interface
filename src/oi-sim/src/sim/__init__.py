"""oi-sim - Virtual DATP device for testing."""

from sim.sim import OiSim, TraceEvent
from sim.state import State, InvalidTransition

__all__ = [
    "OiSim",
    "TraceEvent",
    "State",
    "InvalidTransition",
    "OiSimREPL",
]


def __getattr__(name):
    if name == "OiSimREPL":
        from sim.repl import OiSimREPL
        return OiSimREPL
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
