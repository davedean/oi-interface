#!/usr/bin/env python3
"""
check_pi_rpc_drift.py — fail loudly when upstream Pi RPC spec drifts from inventory.

Parses headings under "## Commands", "## Events", and "## Extension UI Protocol"
in the upstream rpc.md, compares to docs/pi_rpc_protocol_inventory.json, and
exits non-zero on any mismatch.

Run:
    python scripts/check_pi_rpc_drift.py
    python scripts/check_pi_rpc_drift.py --spec /custom/path/rpc.md

Exit codes:
    0 — inventory matches spec
    1 — drift detected (added or removed names)
    2 — usage / IO error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY = REPO_ROOT / "docs" / "pi_rpc_protocol_inventory.json"
DEFAULT_SPEC = (
    Path.home()
    / ".npm-global/lib/node_modules/@mariozechner/pi-coding-agent/docs/rpc.md"
)

# Headings that match the right level but aren't protocol items.
NON_PROTOCOL_NAMES = {
    # Under ## Commands (#### level) — none today.
    # Under ## Events (### level) — table-of-contents heading.
    "Event Types",
    # Under ## Extension UI Protocol (#### level) — response shape sub-headings.
    "Value response (select, input, editor)",
    "Confirmation response (confirm)",
    "Cancellation response (any dialog)",
}

# Per-section heading level: events live at h3, commands and UI methods at h4.
SECTION_LEVELS = {
    "Commands": 4,
    "Events": 3,
    "Extension UI Protocol": 4,
}

# Strip trailing parentheticals like "message_update (Streaming)".
_PAREN_TAIL = re.compile(r"\s*\([^)]*\)\s*$")


def _normalize_event_heading(raw: str) -> list[str]:
    """Events have combined headings like 'turn_start / turn_end'. Split + strip."""
    cleaned = _PAREN_TAIL.sub("", raw).strip()
    parts = [p.strip() for p in cleaned.split("/")]
    return [p for p in parts if p]


def parse_spec(spec_path: Path) -> dict:
    """Walk headings and bucket them by the most recent ## section."""
    if not spec_path.exists():
        print(f"[drift] spec file not found: {spec_path}", file=sys.stderr)
        sys.exit(2)

    sections: dict[str, list[str]] = {name: [] for name in SECTION_LEVELS}
    current_h2: str | None = None

    h2 = re.compile(r"^## (.+?)\s*$")
    hN = re.compile(r"^(#{3,4}) (.+?)\s*$")

    for raw in spec_path.read_text(encoding="utf-8").splitlines():
        m2 = h2.match(raw)
        if m2:
            current_h2 = m2.group(1).strip()
            continue
        if current_h2 not in SECTION_LEVELS:
            continue
        m = hN.match(raw)
        if not m:
            continue
        level = len(m.group(1))
        if level != SECTION_LEVELS[current_h2]:
            continue
        name = m.group(2).strip()
        if name in NON_PROTOCOL_NAMES:
            continue
        if current_h2 == "Events":
            sections["Events"].extend(_normalize_event_heading(name))
        else:
            sections[current_h2].append(name)

    return sections


def load_inventory() -> dict:
    if not INVENTORY.exists():
        print(f"[drift] inventory not found: {INVENTORY}", file=sys.stderr)
        sys.exit(2)
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def diff_sets(label: str, expected: set[str], actual: set[str]) -> list[str]:
    errors: list[str] = []
    missing = expected - actual
    extra = actual - expected
    if missing:
        errors.append(f"[{label}] missing from inventory (in spec, not in inventory): {sorted(missing)}")
    if extra:
        errors.append(f"[{label}] extra in inventory (not in spec): {sorted(extra)}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    args = ap.parse_args()

    spec = parse_spec(args.spec)
    inventory = load_inventory()

    inv_commands = {c["name"] for c in inventory["commands"]}
    inv_events = {e["name"] for e in inventory["events"]}
    inv_ui = {m["name"] for m in inventory["ui_methods"]["dialog"]}
    inv_ui |= {m["name"] for m in inventory["ui_methods"]["fire_and_forget"]}

    spec_commands = set(spec["Commands"])
    spec_events = set(spec["Events"])
    spec_ui = set(spec["Extension UI Protocol"])

    errors: list[str] = []
    errors += diff_sets("commands", spec_commands, inv_commands)
    errors += diff_sets("events", spec_events, inv_events)
    errors += diff_sets("ui_methods", spec_ui, inv_ui)

    if errors:
        print("Pi RPC spec drift detected:\n", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print(
            "\nUpdate docs/pi_rpc_protocol_inventory.json and add builders/projections,\n"
            "or update this script if the spec format itself changed.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Pi RPC inventory matches spec: "
        f"{len(inv_commands)} commands, {len(inv_events)} events, "
        f"{len(inv_ui)} UI methods."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
