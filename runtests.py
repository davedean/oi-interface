#!/usr/bin/env python3
"""Repo-root test runner for oi-v2 subprojects.

Plain English:
- running `pytest` once at repo root is awkward here because multiple subprojects
  each have their own `tests/` package/conftest layout
- this runner executes each v2 subproject test suite in its own intended working
  directory, which avoids cross-project pytest import collisions
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SUITES = [
    ROOT / "src" / "oi-cli",
    ROOT / "src" / "oi-gateway",
    ROOT / "src" / "oi-sim",
    ROOT / "src" / "oi-dashboard",
    ROOT / "src" / "oi-clients",
]


def main() -> int:
    overall_rc = 0
    for suite in SUITES:
        print(f"\n=== pytest: {suite.relative_to(ROOT)} ===", flush=True)
        result = subprocess.run(["pytest", "-q"], cwd=suite)
        if result.returncode != 0:
            overall_rc = result.returncode
    return overall_rc


if __name__ == "__main__":
    raise SystemExit(main())
