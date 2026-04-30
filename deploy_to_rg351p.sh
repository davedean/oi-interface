#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/src/oi-clients/generic_sbc_handheld/deploy.sh" --host anbernic "$@"
