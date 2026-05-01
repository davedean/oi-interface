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
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Suite:
    path: Path
    extra_args: list[str] = field(default_factory=list)


SUITES = [
    Suite(ROOT / "src" / "oi-cli"),
    Suite(ROOT / "src" / "oi-gateway"),
    Suite(ROOT / "src" / "oi-clients" / "oi-sim"),
    Suite(ROOT / "src" / "oi-dashboard"),
    Suite(ROOT / "src" / "oi-clients", ["--ignore=oi-sim"]),
]


def pytest_command() -> list[str]:
    """Use the repo virtualenv when present, otherwise use this interpreter."""
    venv_python = ROOT / ".venv" / "bin" / "python"
    python = venv_python if venv_python.exists() else Path(sys.executable)
    return [str(python), "-m", "pytest", "-q"]


def main() -> int:
    overall_rc = 0
    command = pytest_command()
    print(f"Using pytest via: {' '.join(command)}", flush=True)
    for suite in SUITES:
        print(f"\n=== pytest: {suite.path.relative_to(ROOT)} ===", flush=True)
        result = subprocess.run([*command, *suite.extra_args], cwd=suite.path)
        if result.returncode != 0:
            overall_rc = result.returncode
    return overall_rc


if __name__ == "__main__":
    raise SystemExit(main())
