#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/src/oi-clients"
pytest -q \
  tests/test_datp.py \
  tests/test_state.py \
  tests/test_core_quality.py \
  --cov=oi_client.datp \
  --cov=oi_client.state \
  --cov=oi_client.capabilities \
  --cov=oi_client.delight \
  --cov-report=term-missing \
  --cov-fail-under=95
