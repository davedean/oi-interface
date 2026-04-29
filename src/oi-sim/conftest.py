"""Ensure sibling oi-gateway package is importable in tests."""
from __future__ import annotations

import sys
from pathlib import Path

# Add oi-gateway/src to sys.path so `from datp import ...` works in tests.
_GW_SRC = Path(__file__).resolve().parents[1] / "oi-gateway" / "src"
if str(_GW_SRC) not in sys.path:
    sys.path.insert(0, str(_GW_SRC))
