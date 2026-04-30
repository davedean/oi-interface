#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "[setup] root: ${ROOT_DIR}"

test -d "${VENV_DIR}" || "${PYTHON_BIN}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip wheel setuptools

"${VENV_DIR}/bin/pip" install -e "${ROOT_DIR}/src/oi-gateway[dev,all]"
"${VENV_DIR}/bin/pip" install -e "${ROOT_DIR}/src/oi-sim[dev]"
"${VENV_DIR}/bin/pip" install -e "${ROOT_DIR}/src/oi-dashboard[dev]"
"${VENV_DIR}/bin/pip" install -e "${ROOT_DIR}/src/oi-cli"

echo "[setup] done"
echo "[setup] python: ${VENV_DIR}/bin/python"
