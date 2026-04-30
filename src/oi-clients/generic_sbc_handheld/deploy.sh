#!/usr/bin/env bash
#
# Deploy the generic Oi SBC handheld client to a Linux handheld over SSH.
#
# Usage:
#   ./src/oi-clients/generic_sbc_handheld/deploy.sh --host anbernic
#
# Defaults target AmberELEC / PortMaster-style paths, but can be overridden.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_HOST="anbernic"
TARGET_ROOT="/storage/roms/ports"
APP_DIR_NAME="Oi"
LAUNCHER_NAME="Oi.sh"
HOST="${DEFAULT_HOST}"
DRY_RUN=false
DO_BACKUP=false
DEPLOY_LAUNCHER=true
VERBOSE=false

usage() {
    cat <<EOF
Usage: $(basename "$0") [options]

Options:
  --host HOST         SSH host to deploy to (default: ${DEFAULT_HOST})
  --target-root PATH  Remote ports root (default: ${TARGET_ROOT})
  --app-dir NAME      Remote app directory name under target root (default: ${APP_DIR_NAME})
  --launcher NAME     Remote launcher filename in target root (default: ${LAUNCHER_NAME})
  --dry-run           Print actions without executing them
  --backup            Backup existing device files before deployment
  --no-launcher       Skip deploying launcher script
  --verbose           Show rsync itemized changes
  -h, --help          Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            [[ $# -ge 2 ]] || { echo "ERROR: --host requires a value" >&2; exit 1; }
            HOST="$2"
            shift 2
            ;;
        --target-root)
            [[ $# -ge 2 ]] || { echo "ERROR: --target-root requires a value" >&2; exit 1; }
            TARGET_ROOT="$2"
            shift 2
            ;;
        --app-dir)
            [[ $# -ge 2 ]] || { echo "ERROR: --app-dir requires a value" >&2; exit 1; }
            APP_DIR_NAME="$2"
            shift 2
            ;;
        --launcher)
            [[ $# -ge 2 ]] || { echo "ERROR: --launcher requires a value" >&2; exit 1; }
            LAUNCHER_NAME="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --backup)
            DO_BACKUP=true
            shift
            ;;
        --no-launcher)
            DEPLOY_LAUNCHER=false
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

SOURCE_ROOT="${SCRIPT_DIR}"
SOURCE_CLIENT_DIR="${SOURCE_ROOT}/oi_client"
SOURCE_LAUNCHER="${SOURCE_ROOT}/Oi.sh"
SOURCE_CAPABILITY_PROFILE="${SOURCE_ROOT}/capability-profile.json"
TARGET_DIR="${TARGET_ROOT}/${APP_DIR_NAME}"
TARGET_CLIENT_DIR="${TARGET_DIR}/oi_client"
TARGET_LAUNCHER="${TARGET_ROOT}/${LAUNCHER_NAME}"

run_ssh() {
    local command="$1"
    if [[ "$DRY_RUN" == true ]]; then
        echo "[DRY-RUN] ssh ${HOST} ${command}"
    else
        echo "[EXEC] ssh ${HOST} ${command}"
        ssh "$HOST" "$command"
    fi
}

copy_file() {
    local src="$1"
    local dst="$2"
    if [[ "$DRY_RUN" == true ]]; then
        echo "[DRY-RUN] scp ${src} ${HOST}:${dst}"
    else
        echo "[EXEC] scp ${src} ${HOST}:${dst}"
        scp "$src" "$HOST:$dst"
    fi
}

have_remote_rsync() {
    if [[ "$DRY_RUN" == true ]]; then
        return 0
    fi
    ssh "$HOST" "command -v rsync >/dev/null 2>&1"
}

sync_client_with_rsync() {
    local -a cmd=(
        rsync -rlptDz --delete
        --no-owner --no-group
        --omit-dir-times
        --exclude='__pycache__/'
        --exclude='*.pyc'
        --exclude='*.pyo'
        --exclude='*.so'
        --exclude='oi.log'
    )

    if [[ "$VERBOSE" == true || "$DRY_RUN" == true ]]; then
        cmd+=(--itemize-changes)
    fi

    cmd+=("${SOURCE_CLIENT_DIR}/" "${HOST}:${TARGET_CLIENT_DIR}/")

    echo "=== Syncing oi_client runtime (rsync) ==="
    if [[ "$DRY_RUN" == true ]]; then
        echo "[DRY-RUN] ${cmd[*]}"
        return 0
    fi
    echo "[EXEC] ${cmd[*]}"
    "${cmd[@]}"
}

sync_client_with_tar() {
    echo "=== Syncing oi_client runtime (tar fallback) ==="

    if [[ "$DRY_RUN" == true ]]; then
        echo "[DRY-RUN] tar client tree to ${HOST}:${TARGET_CLIENT_DIR}"
        return 0
    fi

    run_ssh "mkdir -p '${TARGET_CLIENT_DIR}'"
    run_ssh "find '${TARGET_CLIENT_DIR}' -mindepth 1 ! -path '${TARGET_CLIENT_DIR}/oi.log' -delete"

    tar \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='*.pyo' \
        --exclude='*.so' \
        --exclude='oi.log' \
        -C "$SOURCE_CLIENT_DIR" -czf - . \
        | ssh "$HOST" "tar -xzf - -C '${TARGET_CLIENT_DIR}'"
}

verify_exists() {
    local path="$1"
    local label="$2"

    if [[ "$DRY_RUN" == true ]]; then
        echo "  [DRY-RUN] verify ${label}"
        return 0
    fi

    if ssh "$HOST" "test -f '$path'"; then
        echo "  [OK] ${label}"
    else
        echo "  [FAIL] ${label}"
        return 1
    fi
}

echo "=== Oi handheld deployment ==="
echo "Target host:      ${HOST}"
echo "Target root:      ${TARGET_ROOT}"
echo "App dir:          ${APP_DIR_NAME}"
echo "Target dir:       ${TARGET_DIR}"
echo "Launcher:         ${LAUNCHER_NAME}"
echo "Source root:      ${SOURCE_ROOT}"
echo "Deploy launcher:  ${DEPLOY_LAUNCHER}"
echo "Dry run:          ${DRY_RUN}"
echo "Verbose:          ${VERBOSE}"
echo ""

[[ -d "$SOURCE_ROOT" ]] || { echo "ERROR: Source root not found: ${SOURCE_ROOT}" >&2; exit 1; }
[[ -d "$SOURCE_CLIENT_DIR" ]] || { echo "ERROR: Source client dir not found: ${SOURCE_CLIENT_DIR}" >&2; exit 1; }
[[ -f "$SOURCE_LAUNCHER" ]] || { echo "ERROR: Launcher not found: ${SOURCE_LAUNCHER}" >&2; exit 1; }
[[ -f "$SOURCE_CAPABILITY_PROFILE" ]] || { echo "ERROR: Capability profile not found: ${SOURCE_CAPABILITY_PROFILE}" >&2; exit 1; }

if [[ "$DRY_RUN" == true ]]; then
    echo "[DRY-RUN] Skipping connectivity check"
else
    if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" "echo connected" >/dev/null 2>&1; then
        echo "ERROR: Cannot connect to ${HOST}" >&2
        exit 1
    fi
fi

run_ssh "mkdir -p '${TARGET_DIR}' '${TARGET_CLIENT_DIR}' '${TARGET_CLIENT_DIR}/lib'"

if [[ "$DO_BACKUP" == true ]]; then
    timestamp="$(date +%Y%m%d_%H%M%S)"
    backup_dir="${TARGET_DIR}/backup_${timestamp}"
    echo "=== Creating backup ==="
    run_ssh "mkdir -p '${backup_dir}' && if [ -d '${TARGET_CLIENT_DIR}' ]; then cp -r '${TARGET_CLIENT_DIR}' '${backup_dir}/oi_client'; fi && if [ -f '${TARGET_DIR}/capability-profile.json' ]; then cp '${TARGET_DIR}/capability-profile.json' '${backup_dir}/'; fi && if [ -f '${TARGET_LAUNCHER}' ]; then cp '${TARGET_LAUNCHER}' '${backup_dir}/${LAUNCHER_NAME}'; fi"
    echo ""
fi

if have_remote_rsync; then
    sync_client_with_rsync
else
    sync_client_with_tar
fi

echo ""
echo "=== Syncing top-level runtime files ==="
copy_file "$SOURCE_CAPABILITY_PROFILE" "${TARGET_DIR}/capability-profile.json"
if [[ "$DEPLOY_LAUNCHER" == true ]]; then
    copy_file "$SOURCE_LAUNCHER" "$TARGET_LAUNCHER"
    run_ssh "chmod +x '${TARGET_LAUNCHER}'"
fi

echo ""
echo "=== Cleaning device cache and temp files ==="
run_ssh "find '${TARGET_CLIENT_DIR}' -type d -name '__pycache__' -prune -exec rm -rf {} +; find '${TARGET_CLIENT_DIR}' -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete; rm -f /tmp/oi_audio_*.wav /tmp/oi_*.wav"

echo ""
echo "=== Verifying critical runtime files ==="
verify_exists "${TARGET_CLIENT_DIR}/app.py" "oi_client/app.py"
verify_exists "${TARGET_CLIENT_DIR}/datp.py" "oi_client/datp.py"
verify_exists "${TARGET_CLIENT_DIR}/capabilities.py" "oi_client/capabilities.py"
verify_exists "${TARGET_CLIENT_DIR}/device_control.py" "oi_client/device_control.py"
verify_exists "${TARGET_CLIENT_DIR}/telemetry.py" "oi_client/telemetry.py"
verify_exists "${TARGET_CLIENT_DIR}/lib/websockets/__init__.py" "oi_client/lib/websockets/__init__.py"
verify_exists "${TARGET_DIR}/capability-profile.json" "${APP_DIR_NAME}/capability-profile.json"
if [[ "$DEPLOY_LAUNCHER" == true ]]; then
    verify_exists "$TARGET_LAUNCHER" "$LAUNCHER_NAME"
fi

echo ""
echo "=== Deployment complete ==="
echo "Launch on device:"
echo "  ssh ${HOST} 'cd ${TARGET_DIR} && PYTHONPATH=${TARGET_ROOT}/PortMaster/exlibs:${TARGET_CLIENT_DIR}/lib:${TARGET_DIR} PYSDL2_DLL_PATH=/usr/lib python3 -m oi_client'"
echo ""
echo "Log file on device:"
echo "  ${TARGET_CLIENT_DIR}/oi.log"
echo ""
echo "Stop running app:"
echo "  ssh ${HOST} \"pkill -f 'python3.*oi_client'\""
