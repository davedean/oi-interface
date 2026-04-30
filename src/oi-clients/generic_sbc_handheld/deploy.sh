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
DEFAULT_APP_ROOT="/storage/roms/ports"
DEFAULT_LAUNCHER_ROOT="${DEFAULT_APP_ROOT}"
APP_ROOT="${DEFAULT_APP_ROOT}"
LAUNCHER_ROOT="${DEFAULT_LAUNCHER_ROOT}"
APP_ROOT_SET=false
LAUNCHER_ROOT_SET=false
PORTMASTER_ROOT=""
LAYOUT_PROFILE="manual"
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
  --host HOST           SSH host to deploy to (default: ${DEFAULT_HOST})
  --target-root PATH    Remote ports root for both app + launcher (legacy)
  --app-root PATH       Remote app payload root (default: auto / ${DEFAULT_APP_ROOT})
  --launcher-root PATH  Remote launcher root (default: auto / ${DEFAULT_LAUNCHER_ROOT})
  --app-dir NAME        Remote app directory name under app root (default: ${APP_DIR_NAME})
  --launcher NAME       Remote launcher filename in launcher root (default: ${LAUNCHER_NAME})
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
            APP_ROOT="$2"
            LAUNCHER_ROOT="$2"
            APP_ROOT_SET=true
            LAUNCHER_ROOT_SET=true
            shift 2
            ;;
        --app-root)
            [[ $# -ge 2 ]] || { echo "ERROR: --app-root requires a value" >&2; exit 1; }
            APP_ROOT="$2"
            APP_ROOT_SET=true
            shift 2
            ;;
        --launcher-root)
            [[ $# -ge 2 ]] || { echo "ERROR: --launcher-root requires a value" >&2; exit 1; }
            LAUNCHER_ROOT="$2"
            LAUNCHER_ROOT_SET=true
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
SOURCE_LAUNCHER_TEMPLATE="${SOURCE_ROOT}/Oi.sh"
SOURCE_CAPABILITY_PROFILE="${SOURCE_ROOT}/capability-profile.json"
DEFAULT_DEVICE_ID="$(printf '%s' "${APP_DIR_NAME}" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-')-001"

compute_target_paths() {
    TARGET_DIR="${APP_ROOT}/${APP_DIR_NAME}"
    TARGET_CLIENT_DIR="${TARGET_DIR}/oi_client"
    TARGET_LAUNCHER="${LAUNCHER_ROOT}/${LAUNCHER_NAME}"
}

have_remote_rsync() {
    if [[ "$DRY_RUN" == true ]]; then
        return 0
    fi
    ssh "$HOST" "command -v rsync >/dev/null 2>&1"
}

resolve_remote_layout() {
    if [[ "$APP_ROOT_SET" == true && "$LAUNCHER_ROOT_SET" == true ]]; then
        compute_target_paths
        return 0
    fi

    if [[ "$DRY_RUN" == true ]]; then
        compute_target_paths
        return 0
    fi

    local detected detected_app_root detected_launcher_root requested_app_root requested_launcher_root
    requested_app_root="$APP_ROOT"
    requested_launcher_root="$LAUNCHER_ROOT"

    detected="$(ssh "$HOST" '
        if [ -d /mnt/mmc/MUOS/PortMaster ] && [ -d /mnt/mmc/ports ] && [ -d /mnt/mmc/ROMS/PORTS ]; then
            printf "APP_ROOT=/mnt/mmc/ports\nLAUNCHER_ROOT=/mnt/mmc/ROMS/PORTS\nPORTMASTER_ROOT=/mnt/mmc/MUOS/PortMaster\nLAYOUT_PROFILE=muOS\n"
        elif [ -d /storage/roms/ports/PortMaster ]; then
            printf "APP_ROOT=/storage/roms/ports\nLAUNCHER_ROOT=/storage/roms/ports\nPORTMASTER_ROOT=/storage/roms/ports/PortMaster\nLAYOUT_PROFILE=amberelec\n"
        elif [ -d /roms/ports/PortMaster ]; then
            printf "APP_ROOT=/roms/ports\nLAUNCHER_ROOT=/roms/ports\nPORTMASTER_ROOT=/roms/ports/PortMaster\nLAYOUT_PROFILE=roms-ports\n"
        else
            exit 1
        fi
    ' 2>/dev/null)" || {
        echo "ERROR: Could not detect remote handheld layout. Use --app-root and --launcher-root." >&2
        exit 1
    }

    eval "$detected"
    detected_app_root="$APP_ROOT"
    detected_launcher_root="$LAUNCHER_ROOT"

    if [[ "$APP_ROOT_SET" == true ]]; then
        APP_ROOT="$requested_app_root"
    else
        APP_ROOT="$detected_app_root"
    fi
    if [[ "$LAUNCHER_ROOT_SET" == true ]]; then
        LAUNCHER_ROOT="$requested_launcher_root"
    else
        LAUNCHER_ROOT="$detected_launcher_root"
    fi

    compute_target_paths
}

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

generate_launcher() {
    local out="$1"
    sed \
        -e "s#__OI_APP_DIR__#${APP_DIR_NAME}#g" \
        -e "s#__OI_DEFAULT_DEVICE_ID__#${DEFAULT_DEVICE_ID}#g" \
        "$SOURCE_LAUNCHER_TEMPLATE" > "$out"
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

compute_target_paths

echo "=== Oi handheld deployment ==="
echo "Target host:      ${HOST}"
echo "App root:         ${APP_ROOT}"
echo "Launcher root:    ${LAUNCHER_ROOT}"
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
[[ -f "$SOURCE_LAUNCHER_TEMPLATE" ]] || { echo "ERROR: Launcher template not found: ${SOURCE_LAUNCHER_TEMPLATE}" >&2; exit 1; }
[[ -f "$SOURCE_CAPABILITY_PROFILE" ]] || { echo "ERROR: Capability profile not found: ${SOURCE_CAPABILITY_PROFILE}" >&2; exit 1; }

if [[ "$DRY_RUN" == true ]]; then
    echo "[DRY-RUN] Skipping connectivity check"
else
    if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$HOST" "echo connected" >/dev/null 2>&1; then
        echo "ERROR: Cannot connect to ${HOST}" >&2
        exit 1
    fi
fi

resolve_remote_layout

echo "Resolved layout:  ${LAYOUT_PROFILE}"
if [[ -n "$PORTMASTER_ROOT" ]]; then
    echo "PortMaster root:  ${PORTMASTER_ROOT}"
fi
echo "App root:         ${APP_ROOT}"
echo "Launcher root:    ${LAUNCHER_ROOT}"
echo "Target dir:       ${TARGET_DIR}"
echo "Launcher path:    ${TARGET_LAUNCHER}"
echo ""

run_ssh "mkdir -p '${TARGET_DIR}' '${TARGET_CLIENT_DIR}' '${TARGET_CLIENT_DIR}/lib' '${LAUNCHER_ROOT}'"

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
    tmp_launcher="$(mktemp)"
    generate_launcher "$tmp_launcher"
    copy_file "$tmp_launcher" "$TARGET_LAUNCHER"
    rm -f "$tmp_launcher"
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
echo "Launch on device via launcher:"
echo "  ${TARGET_LAUNCHER}"
echo ""
echo "Manual Python run on device (after setting PortMaster PYTHONPATH):"
if [[ -n "$PORTMASTER_ROOT" ]]; then
    echo "  ssh ${HOST} 'cd ${TARGET_DIR} && PYTHONPATH=${PORTMASTER_ROOT}/exlibs:${TARGET_CLIENT_DIR}/lib:${TARGET_DIR} PYSDL2_DLL_PATH=/usr/lib python3 -m oi_client'"
else
    echo "  ssh ${HOST} 'cd ${TARGET_DIR} && PYTHONPATH=<portmaster-exlibs>:${TARGET_CLIENT_DIR}/lib:${TARGET_DIR} PYSDL2_DLL_PATH=/usr/lib python3 -m oi_client'"
fi
echo ""
echo "Log file on device:"
echo "  ${TARGET_CLIENT_DIR}/oi.log"
echo ""
echo "Stop running app:"
echo "  ssh ${HOST} \"pkill -f 'python3.*oi_client'\""
