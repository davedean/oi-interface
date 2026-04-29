#!/usr/bin/env bash
# Runs all Pi RPC parity gates in order. Exits non-zero if any fails.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[gate 1/4] drift detector"
python3 scripts/check_pi_rpc_drift.py

echo "[gate 2/4] python tests"
python3 -m pytest -q

echo "[gate 3/4] mock-device tests"
npm run test:mock-device

echo "[gate 4/4] fake-peer harness"
npm run test:harness

echo ""
echo "[OK] all Pi RPC parity gates passed"
