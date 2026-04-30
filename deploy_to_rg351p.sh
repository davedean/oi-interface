#!/usr/bin/env bash
#
# Deploy Oi handheld client to RG351P / AmberELEC-style devices.
#
# Usage:
#   ./deploy_to_rg351p.sh [--dry-run] [--backup] [--host HOST] [--no-launcher]
#
# Default host: anbernic
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_HOST="anbernic"
TARGET_ROOT="/storage/roms/ports"
TARGET_DIR="${TARGET_ROOT}/Oi"
TARGET_CLIENT_DIR="${TARGET_DIR}/oi_client"
TARGET_LAUNCHER="${TARGET_ROOT}/Oi.sh"
SOURCE_ROOT="${SCRIPT_DIR}/src/oi-clients/generic_sbc_handheld"
SOURCE_CLIENT_DIR="${SOURCE_ROOT}/oi_client"
SOURCE_LAUNCHER="${SOURCE_ROOT}/Oi.sh"
SOURCE_CAPABILITY_PROFILE="${SOURCE_ROOT}/capability-profile.json"

DRY_RUN=false
DO_BACKUP=false
DEPLOY_LAUNCHER=true
HOST="${DEFAULT_HOST}"

usage() {
    cat <<EOF
Usage: ./deploy_to_rg351p.sh [options]

Options:
  --host HOST      SSH host to deploy to (default: ${DEFAULT_HOST})
  --dry-run        Print actions without executing them
  --backup         Backup existing device files before deployment
  --no-launcher    Skip deploying Oi.sh launcher
  -h, --help       Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            [[ $# -ge 2 ]] || { echo "ERROR: --host requires a value" >&2; exit 1; }
            HOST="$2"
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

remote_md5() {
    local path="$1"
    if [[ "$DRY_RUN" == true ]]; then
        return 0
    fi
    ssh "$HOST" "md5sum '$path' 2>/dev/null | awk '{print \$1}'" 2>/dev/null || true
}

copy_if_changed() {
    local src="$1"
    local dst="$2"
    local label="$3"
    local local_hash remote_hash

    if [[ ! -f "$src" ]]; then
        echo "  [WARN] missing local file: ${src}"
        return 1
    fi

    local_hash="$(md5sum "$src" | awk '{print $1}')"
    remote_hash="$(remote_md5 "$dst")"

    if [[ "$local_hash" == "$remote_hash" && -n "$remote_hash" ]]; then
        echo "  [SKIP] ${label}"
        return 0
    fi

    echo "  [COPY] ${label}"
    copy_file "$src" "$dst"
}

verify_match() {
    local src="$1"
    local dst="$2"
    local label="$3"
    local local_hash remote_hash

    if [[ "$DRY_RUN" == true ]]; then
        echo "  [DRY-RUN] verify ${label}"
        return 0
    fi

    local_hash="$(md5sum "$src" | awk '{print $1}')"
    remote_hash="$(remote_md5 "$dst")"

    if [[ "$local_hash" == "$remote_hash" && -n "$remote_hash" ]]; then
        echo "  [OK] ${label}"
    else
        echo "  [FAIL] ${label}"
        return 1
    fi
}

echo "=== Oi handheld deployment ==="
echo "Target host:      ${HOST}"
echo "Target root:      ${TARGET_ROOT}"
echo "Target dir:       ${TARGET_DIR}"
echo "Source root:      ${SOURCE_ROOT}"
echo "Deploy launcher:  ${DEPLOY_LAUNCHER}"
echo "Dry run:          ${DRY_RUN}"
echo ""

[[ -d "$SOURCE_ROOT" ]] || { echo "ERROR: Source root not found: ${SOURCE_ROOT}" >&2; exit 1; }
[[ -d "$SOURCE_CLIENT_DIR" ]] || { echo "ERROR: Source client dir not found: ${SOURCE_CLIENT_DIR}" >&2; exit 1; }
[[ -f "$SOURCE_LAUNCHER" ]] || { echo "ERROR: Launcher not found: ${SOURCE_LAUNCHER}" >&2; exit 1; }

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
    run_ssh "mkdir -p '${backup_dir}' && if [ -d '${TARGET_CLIENT_DIR}' ]; then cp -r '${TARGET_CLIENT_DIR}' '${backup_dir}/oi_client'; fi && if [ -f '${TARGET_DIR}/capability-profile.json' ]; then cp '${TARGET_DIR}/capability-profile.json' '${backup_dir}/'; fi && if [ -f '${TARGET_LAUNCHER}' ]; then cp '${TARGET_LAUNCHER}' '${backup_dir}/Oi.sh'; fi"
    echo ""
fi

echo "=== Syncing oi_client runtime ==="
mapfile -t CLIENT_FILES < <(cd "$SOURCE_CLIENT_DIR" && find . -type f \
    ! -path './__pycache__/*' \
    ! -path './lib/__pycache__/*' \
    ! -name '*.pyc' \
    ! -name '*.pyo' \
    ! -name '*.so' \
    ! -name 'oi.log' | sort)

for rel in "${CLIENT_FILES[@]}"; do
    rel="${rel#./}"
    src="${SOURCE_CLIENT_DIR}/${rel}"
    dst="${TARGET_CLIENT_DIR}/${rel}"
    dst_dir="$(dirname "$dst")"
    run_ssh "mkdir -p '${dst_dir}'"
    copy_if_changed "$src" "$dst" "oi_client/${rel}"
done

echo ""
echo "=== Pruning stale runtime files ==="
if [[ "$DRY_RUN" == true ]]; then
    echo "  [DRY-RUN] skip remote prune"
else
    declare -A LOCAL_CLIENT_SET=()
    for rel in "${CLIENT_FILES[@]}"; do
        LOCAL_CLIENT_SET["${rel#./}"]=1
    done
    while IFS= read -r remote_rel; do
        remote_rel="${remote_rel#./}"
        [[ -n "$remote_rel" ]] || continue
        if [[ -z "${LOCAL_CLIENT_SET[$remote_rel]+x}" ]]; then
            echo "  [DELETE] oi_client/${remote_rel}"
            run_ssh "rm -f '${TARGET_CLIENT_DIR}/${remote_rel}'"
        fi
    done < <(ssh "$HOST" "cd '${TARGET_CLIENT_DIR}' && find . -type f ! -name 'oi.log' ! -name '*.pyc' ! -name '*.pyo' | sort")
fi

echo ""
echo "=== Syncing top-level runtime files ==="
copy_if_changed "$SOURCE_CAPABILITY_PROFILE" "${TARGET_DIR}/capability-profile.json" "Oi/capability-profile.json"
if [[ "$DEPLOY_LAUNCHER" == true ]]; then
    copy_if_changed "$SOURCE_LAUNCHER" "$TARGET_LAUNCHER" "Oi.sh"
    run_ssh "chmod +x '${TARGET_LAUNCHER}'"
fi

echo ""
echo "=== Cleaning device cache and temp files ==="
run_ssh "find '${TARGET_CLIENT_DIR}' -type d -name '__pycache__' -prune -exec rm -rf {} +; find '${TARGET_CLIENT_DIR}' -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete; rm -f /tmp/oi_audio_*.wav /tmp/oi_*.wav"

echo ""
echo "=== Verifying critical runtime files ==="
verify_match "${SOURCE_CLIENT_DIR}/app.py" "${TARGET_CLIENT_DIR}/app.py" "oi_client/app.py"
verify_match "${SOURCE_CLIENT_DIR}/datp.py" "${TARGET_CLIENT_DIR}/datp.py" "oi_client/datp.py"
verify_match "${SOURCE_CLIENT_DIR}/capabilities.py" "${TARGET_CLIENT_DIR}/capabilities.py" "oi_client/capabilities.py"
verify_match "${SOURCE_CLIENT_DIR}/device_control.py" "${TARGET_CLIENT_DIR}/device_control.py" "oi_client/device_control.py"
verify_match "${SOURCE_CLIENT_DIR}/telemetry.py" "${TARGET_CLIENT_DIR}/telemetry.py" "oi_client/telemetry.py"
if [[ "$DEPLOY_LAUNCHER" == true ]]; then
    verify_match "$SOURCE_LAUNCHER" "$TARGET_LAUNCHER" "Oi.sh"
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
