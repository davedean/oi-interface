# SDL2 Smoke Tests (Manual Only)

This directory contains manual hardware smoke checks for the generic SBC handheld client.

- These scripts are **not** part of automated pytest runs.
- Run them manually on target hardware (or a suitable SDL2 environment) during bring-up/debugging.

## Naming

- `smoke_*.py` files are manual checks.
- Do not name files here as `test_*.py` to avoid pytest auto-collection.
