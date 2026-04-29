"""
Set-coverage tests against docs/pi_rpc_protocol_inventory.json.

These are the "are we done?" oracle for Pi RPC parity work. They:

- Load the canonical inventory (29 commands, 16 events, 9 UI methods).
- Try to import firmware/lib/pi_rpc_commands.py / pi_rpc_events.py / pi_rpc_protocol.py
  (created in Step 2 of PI_RPC_FULL_PARITY_PLAN.md).
- Diff each implementation registry against the inventory.

Until Step 2 lands, the imports fail and the test reports the missing module.
After Step 2, the tests fail with an explicit list of unimplemented items.
That list shrinks to empty as Steps 3, 4, 5 land.

Modules expected (Track A — firmware):
    firmware/lib/pi_rpc_commands.py
        COMMAND_BUILDERS: dict[str, Callable[..., dict]]
            One entry per command. Builder returns a wire-shape dict.
    firmware/lib/pi_rpc_events.py
        EVENT_PROJECTIONS: dict[str, Callable[[dict, dict], dict]]
            One entry per event. Pure: (state, msg) -> new_state.
    firmware/lib/pi_rpc_protocol.py
        UI_METHOD_HANDLERS: dict[str, Callable]
            One entry per UI method (dialog + fire-and-forget).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = REPO_ROOT / "docs" / "pi_rpc_protocol_inventory.json"
FIRMWARE_LIB = REPO_ROOT / "firmware" / "lib"
if str(FIRMWARE_LIB) not in sys.path:
    sys.path.insert(0, str(FIRMWARE_LIB))


def _load_inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def _expected_commands(inv: dict) -> set[str]:
    return {c["name"] for c in inv["commands"]}


def _expected_events(inv: dict) -> set[str]:
    return {e["name"] for e in inv["events"]}


def _expected_ui_methods(inv: dict) -> set[str]:
    out: set[str] = set()
    out |= {m["name"] for m in inv["ui_methods"]["dialog"]}
    out |= {m["name"] for m in inv["ui_methods"]["fire_and_forget"]}
    return out


def _try_import(module_name: str, attr: str) -> tuple[dict | None, str | None]:
    """Return (registry, error_message). Registry is None if import failed."""
    try:
        module = __import__(module_name, fromlist=[attr])
    except ImportError as e:
        return None, f"module {module_name!r} not importable yet: {e}"
    registry = getattr(module, attr, None)
    if registry is None:
        return None, f"module {module_name!r} loaded but {attr!r} attribute is missing"
    if not isinstance(registry, dict):
        return None, f"{module_name}.{attr} is {type(registry).__name__}, expected dict"
    return registry, None


class CommandCoverage(unittest.TestCase):
    def test_command_builders_match_inventory(self):
        inv = _load_inventory()
        expected = _expected_commands(inv)

        registry, err = _try_import("pi_rpc_commands", "COMMAND_BUILDERS")
        if err:
            self.fail(
                f"Command coverage gate cannot evaluate: {err}\n"
                "Expected commands: " + ", ".join(sorted(expected))
            )

        actual = set(registry.keys())
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)

        if missing or extra:
            msg = ["Command builder set does not match inventory."]
            if missing:
                msg.append(f"  missing ({len(missing)}): {missing}")
            if extra:
                msg.append(f"  extra ({len(extra)}): {extra}")
            self.fail("\n".join(msg))


class EventCoverage(unittest.TestCase):
    def test_event_projections_match_inventory(self):
        inv = _load_inventory()
        expected = _expected_events(inv)

        registry, err = _try_import("pi_rpc_events", "EVENT_PROJECTIONS")
        if err:
            self.fail(
                f"Event coverage gate cannot evaluate: {err}\n"
                "Expected events: " + ", ".join(sorted(expected))
            )

        actual = set(registry.keys())
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)

        if missing or extra:
            msg = ["Event projection set does not match inventory."]
            if missing:
                msg.append(f"  missing ({len(missing)}): {missing}")
            if extra:
                msg.append(f"  extra ({len(extra)}): {extra}")
            self.fail("\n".join(msg))


class UiMethodCoverage(unittest.TestCase):
    def test_ui_method_handlers_match_inventory(self):
        inv = _load_inventory()
        expected = _expected_ui_methods(inv)

        registry, err = _try_import("pi_rpc_protocol", "UI_METHOD_HANDLERS")
        if err:
            self.fail(
                f"UI method coverage gate cannot evaluate: {err}\n"
                "Expected UI methods: " + ", ".join(sorted(expected))
            )

        actual = set(registry.keys())
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)

        if missing or extra:
            msg = ["UI method handler set does not match inventory."]
            if missing:
                msg.append(f"  missing ({len(missing)}): {missing}")
            if extra:
                msg.append(f"  extra ({len(extra)}): {extra}")
            self.fail("\n".join(msg))


class CasingTrap(unittest.TestCase):
    """Guard against well-meaning normalization of UI method names."""

    def test_camelcase_dialog_setters_present_in_inventory(self):
        inv = _load_inventory()
        names = _expected_ui_methods(inv)
        for camel in ("setStatus", "setWidget", "setTitle"):
            self.assertIn(camel, names, f"{camel} must remain camelCase, not normalized")

    def test_snake_case_set_editor_text_present_in_inventory(self):
        inv = _load_inventory()
        names = _expected_ui_methods(inv)
        self.assertIn("set_editor_text", names, "set_editor_text must remain snake_case")


if __name__ == "__main__":
    unittest.main()
