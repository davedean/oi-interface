"""pytest configuration: ensure `src` is on the import path."""
from __future__ import annotations

import sys
from pathlib import Path

# rootdir is oi-gateway/; add oi-gateway/src so `from datp import ...` works
src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)
