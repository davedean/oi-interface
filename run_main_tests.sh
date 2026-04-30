#!/usr/bin/env bash
set -euo pipefail

# Scope for this run: changed non-oi-clients package(s).
# Currently that is oi-cli.
cd "$(dirname "$0")/src/oi-cli"
pytest -q tests/test_cli.py tests/test_cli_coverage.py \
  --cov=oi_cli \
  --cov-report=term-missing \
  --cov-fail-under=95
