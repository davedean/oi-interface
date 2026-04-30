#!/usr/bin/env bash
#
# Oi Gateway + Agent Backend Manager
# Starts/stops/checks status of oi-gateway with a selected backend:
# pi, hermes, or openclaw.
#
# Usage:
#   ./start-oi.sh start [backend]    - Start gateway with backend (default: pi)
#   ./start-oi.sh stop               - Stop gateway
#   ./start-oi.sh status [backend]   - Check status and selected backend
#   ./start-oi.sh restart [backend]  - Restart gateway with backend
#   ./start-oi.sh logs               - Show recent logs
#   ./start-oi.sh test [backend|all] - Validate backend config and connectivity
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY_DIR="${SCRIPT_DIR}/src/oi-gateway"
VENV_DIR="${SCRIPT_DIR}/.venv"
resolve_oi_home() {
    if [[ -n "${OI_HOME:-}" ]]; then
        echo "${OI_HOME}"
    elif [[ -n "${XDG_CONFIG_HOME:-}" ]]; then
        echo "${XDG_CONFIG_HOME}/oi"
    else
        echo "${HOME}/.oi"
    fi
}

OI_HOME_DIR="$(resolve_oi_home)"
OI_CONFIG_DIR="${OI_HOME_DIR}/config/oi-gateway"
OI_SECRETS_DIR="${OI_HOME_DIR}/secrets/oi-gateway"
OI_STATE_DIR="${OI_HOME_DIR}/state/oi-gateway"
OI_LOGS_DIR="${OI_HOME_DIR}/logs/oi-gateway"
PID_DIR="${OI_STATE_DIR}"
GATEWAY_PID="${PID_DIR}/gateway.pid"
GATEWAY_PORT=8787
GATEWAY_HOST="0.0.0.0"
LOG_FILE="${OI_LOGS_DIR}/gateway.log"
BACKEND_DEFAULT="${OI_AGENT_BACKEND:-pi}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ------------------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------------------

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_err()   { echo -e "${RED}[ERR]${NC}   $*"; }

python_cmd() {
    if [[ -x "${VENV_DIR}/bin/python" ]]; then
        echo "${VENV_DIR}/bin/python"
    else
        echo "python3"
    fi
}

pip_cmd() {
    if [[ -x "${VENV_DIR}/bin/pip" ]]; then
        echo "${VENV_DIR}/bin/pip"
    else
        echo "python3 -m pip"
    fi
}

mkdir -p "${PID_DIR}"
mkdir -p "${OI_LOGS_DIR}"
mkdir -p "${OI_CONFIG_DIR}"
mkdir -p "${OI_SECRETS_DIR}"

normalize_backend() {
    local backend="${1:-${BACKEND_DEFAULT}}"
    backend="${backend,,}"
    case "${backend}" in
        pi|hermes|openclaw)
            echo "${backend}"
            ;;
        *)
            log_err "Unsupported backend: ${backend}"
            echo ""
            return 1
            ;;
    esac
}

source_env_file() {
    local file="$1"
    if [[ -f "${file}" ]]; then
        log_info "Loading env file: ${file}"
        # shellcheck disable=SC1090
        set -a
        source "${file}"
        set +a
    fi
}

source_toml_env() {
    local file="$1"
    if [[ -f "${file}" ]]; then
        log_info "Loading TOML config: ${file}"
        local py
        py="$(python_cmd)"
        # Export top-level KEY="value" pairs and [env] table entries.
        while IFS= read -r line; do
            eval "export ${line}"
        done < <("${py}" - "$file" <<'PY'
import sys, tomllib
from pathlib import Path
p=Path(sys.argv[1])
obj=tomllib.loads(p.read_text())
items={}
for k,v in obj.items():
    if isinstance(v,(str,int,float,bool)):
        items[k]=v
env=obj.get("env")
if isinstance(env,dict):
    for k,v in env.items():
        if isinstance(v,(str,int,float,bool)):
            items[k]=v
for k,v in items.items():
    sval=str(v).replace('"','\\"')
    print(f'{k}="{sval}"')
PY
)
    fi
}

source_legacy_backend_env() {
    local backend="$1"

    source_env_file "${SCRIPT_DIR}/.env.local"
    source_env_file "${GATEWAY_DIR}/.env.local"
    source_env_file "${GATEWAY_DIR}/${backend}.env.local"
}

prepare_backend_env() {
    local backend
    backend="$(normalize_backend "${1:-${BACKEND_DEFAULT}}")"

    export OI_HOME="${OI_HOME_DIR}"
    export OI_AGENT_BACKEND="${backend}"
    source_toml_env "${OI_CONFIG_DIR}/config.toml"
    source_toml_env "${OI_SECRETS_DIR}/secrets.toml"
    source_toml_env "${OI_CONFIG_DIR}/${backend}.toml"
    source_toml_env "${OI_SECRETS_DIR}/${backend}.toml"

    source_env_file "${OI_SECRETS_DIR}/${backend}.env.local"
    source_env_file "${OI_CONFIG_DIR}/${backend}.env.local"

    case "${backend}" in
        pi)
            ;;
        hermes)
            if [[ -z "${OI_HERMES_BASE_URL:-}" || -z "${OI_HERMES_API_KEY:-}" ]]; then
                source_legacy_backend_env "${backend}"
                source_env_file "${OI_CONFIG_DIR}/hermes.env.local"
            fi
            if [[ -z "${OI_HERMES_BASE_URL:-}" || -z "${OI_HERMES_API_KEY:-}" ]]; then
                return 1
            fi
            ;;
        openclaw)
            if [[ -z "${OI_OPENCLAW_TOKEN:-}" && -n "${OPENCLAW_GATEWAY_TOKEN:-}" ]]; then
                export OI_OPENCLAW_TOKEN="${OPENCLAW_GATEWAY_TOKEN}"
            fi
            if [[ -z "${OI_OPENCLAW_TOKEN:-}" ]]; then
                source_legacy_backend_env "${backend}"
                source_env_file "${OI_CONFIG_DIR}/openclaw.env.local"
                if [[ -z "${OI_OPENCLAW_TOKEN:-}" && -n "${OPENCLAW_GATEWAY_TOKEN:-}" ]]; then
                    export OI_OPENCLAW_TOKEN="${OPENCLAW_GATEWAY_TOKEN}"
                fi
            fi
            export OI_OPENCLAW_URL="${OI_OPENCLAW_URL:-ws://127.0.0.1:18789}"
            if [[ -z "${OI_OPENCLAW_TOKEN:-}" ]]; then
                return 1
            fi
            ;;
    esac
}

validate_backend_config() (
    local backend
    backend="$(normalize_backend "${1:-${BACKEND_DEFAULT}}")"
    if [[ -z "${backend}" ]]; then
        exit 1
    fi

    if ! prepare_backend_env "${backend}" >/dev/null 2>&1; then
        exit 1
    fi

    cd "${GATEWAY_DIR}" || exit 1
    local py
    py="$(python_cmd)"
    PYTHONPATH="${GATEWAY_DIR}/src" "${py}" -c "
from channel.factory import create_backend_from_env
backend = create_backend_from_env()
print(type(backend).__name__)
"
)

# ------------------------------------------------------------------------------
# Process detection
# ------------------------------------------------------------------------------

is_gateway_running() {
    if [[ -f "${GATEWAY_PID}" ]]; then
        local pid
        pid=$(cat "${GATEWAY_PID}")
        if kill -0 "${pid}" 2>/dev/null; then
            # Double-check it's actually our gateway
            if ps -p "${pid}" -o comm= 2>/dev/null | grep -q python; then
                return 0
            fi
        fi
    fi
    return 1
}

is_port_listening() {
    local port=$1
    if nc -z localhost "${port}" 2>/dev/null || \
       "$(python_cmd)" -c "import socket; s=socket.socket(); s.settimeout(1); r=s.connect_ex(('localhost',${port})); s.close(); exit(0 if r==0 else 1)" 2>/dev/null; then
        return 0
    fi
    return 1
}

get_gateway_pid() {
    if is_gateway_running; then
        cat "${GATEWAY_PID}"
    else
        echo ""
    fi
}

# Also try to find gateway by port as fallback
find_gateway_by_port() {
    if is_port_listening "${GATEWAY_PORT}"; then
        # Get PID listening on port
        if command -v lsof &>/dev/null; then
            lsof -ti :"${GATEWAY_PORT}" -sTCP:LISTEN 2>/dev/null | head -1
        elif command -v ss &>/dev/null; then
            ss -tlnp 2>/dev/null | grep ":${GATEWAY_PORT}" | grep -oP 'pid=\K[0-9]+' | head -1
        elif command -v netstat &>/dev/null; then
            netstat -tlnp 2>/dev/null | grep ":${GATEWAY_PORT}" | awk '{print $7}' | grep -oP '[0-9]+(?=/)' | head -1
        fi
    fi
    echo ""
}

# ------------------------------------------------------------------------------
# Pi agent detection
# ------------------------------------------------------------------------------

is_pi_available() {
    if command -v pi &>/dev/null || command -v openclaw &>/dev/null; then
        return 0
    fi
    return 1
}

get_pi_cmd() {
    if command -v openclaw &>/dev/null; then
        echo "openclaw"
    elif command -v pi &>/dev/null; then
        echo "pi"
    else
        echo ""
    fi
}

# ------------------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------------------

cmd_start() {
    local backend
    backend="$(normalize_backend "${2:-${BACKEND_DEFAULT}}")"
    if [[ -z "${backend}" ]]; then
        exit 1
    fi

    if ! prepare_backend_env "${backend}"; then
        log_err "Missing required env for backend '${backend}'"
        case "${backend}" in
            hermes)
                log_err "Need OI_HERMES_BASE_URL and OI_HERMES_API_KEY"
                log_info "See: ${GATEWAY_DIR}/hermes.env.example"
                ;;
            openclaw)
                log_err "Need OI_OPENCLAW_TOKEN (or OPENCLAW_GATEWAY_TOKEN)"
                log_info "See: ${GATEWAY_DIR}/openclaw.env.example"
                ;;
        esac
        exit 1
    fi

    log_info "Starting Oi Gateway + Agent stack (${backend})..."
    echo ""

    # Check if already running (via PID file or port)
    if is_gateway_running; then
        log_warn "Gateway is already running (PID: $(get_gateway_pid))"
    elif is_port_listening "${GATEWAY_PORT}"; then
        local pid
        pid=$(find_gateway_by_port)
        if [[ -n "${pid}" ]]; then
            log_warn "Gateway is already running on port ${GATEWAY_PORT} (PID: ${pid})"
            echo "${pid}" > "${GATEWAY_PID}"
        fi
    fi

    if ! is_gateway_running && ! is_port_listening "${GATEWAY_PORT}"; then
        log_info "Starting oi-gateway on ${GATEWAY_HOST}:${GATEWAY_PORT}..."
        cd "${GATEWAY_DIR}" || { log_err "Cannot cd to ${GATEWAY_DIR}"; exit 1; }

        # Start gateway in background using the real runtime bootstrap.
        cd "${GATEWAY_DIR}"
        nohup env \
            OI_HOME="${OI_HOME_DIR}" \
            OI_AGENT_BACKEND="${backend}" \
            OI_GATEWAY_HOST="${GATEWAY_HOST}" \
            OI_GATEWAY_PORT="${GATEWAY_PORT}" \
            OI_GATEWAY_API_HOST="${GATEWAY_HOST}" \
            OI_GATEWAY_API_PORT="8788" \
            OI_HERMES_BASE_URL="${OI_HERMES_BASE_URL:-}" \
            OI_HERMES_API_KEY="${OI_HERMES_API_KEY:-}" \
            OI_HERMES_MODEL="${OI_HERMES_MODEL:-hermes}" \
            OI_OPENCLAW_URL="${OI_OPENCLAW_URL:-ws://127.0.0.1:18789}" \
            OI_OPENCLAW_TOKEN="${OI_OPENCLAW_TOKEN:-}" \
            OI_OPENCLAW_TIMEOUT_SECONDS="${OI_OPENCLAW_TIMEOUT_SECONDS:-120}" \
            PYTHONPATH="${GATEWAY_DIR}/src" \
            "$(python_cmd)" -m gateway_app \
            >> "${LOG_FILE}" 2>&1 &

        local gateway_pid=$!
        echo "${gateway_pid}" > "${GATEWAY_PID}"

        # Wait a moment and verify it started
        sleep 2
        if kill -0 "${gateway_pid}" 2>/dev/null; then
            log_ok "Gateway started (PID: ${gateway_pid})"
        else
            log_err "Gateway failed to start. Check ${LOG_FILE}"
            echo "--- Last 20 lines of log ---"
            tail -20 "${LOG_FILE}" 2>/dev/null || true
            rm -f "${GATEWAY_PID}"
            exit 1
        fi
    else
        local pid
        pid=$(get_gateway_pid)
        [[ -z "${pid}" ]] && pid=$(find_gateway_by_port)
        log_ok "Gateway already running (PID: ${pid:-unknown})"
    fi

    echo ""

    log_info "Selected backend: ${backend}"
    case "${backend}" in
        pi)
            if is_pi_available; then
                log_ok "Pi command available: $(get_pi_cmd)"
            else
                log_warn "Pi command not found"
            fi
            ;;
        hermes)
            log_ok "Hermes base URL: ${OI_HERMES_BASE_URL}"
            ;;
        openclaw)
            log_ok "OpenClaw URL: ${OI_OPENCLAW_URL}"
            ;;
    esac

    echo ""
    log_info "Gateway URL: ws://localhost:${GATEWAY_PORT}/datp"
    log_info "REST API:   http://localhost:8788/api/health"
    log_info ""
    log_info "Test with oi-sim:"
    log_info "  cd src/oi-sim && PYTHONPATH=src python3 -m sim.repl"
    echo ""
}

cmd_stop() {
    log_info "Stopping Oi Gateway..."

    if is_gateway_running; then
        local pid
        pid=$(get_gateway_pid)
        log_info "Stopping gateway (PID: ${pid})..."
        kill "${pid}" 2>/dev/null || true
        sleep 1
        # Force kill if still running
        if kill -0 "${pid}" 2>/dev/null; then
            log_warn "Gateway still running, forcing..."
            kill -9 "${pid}" 2>/dev/null || true
        fi
        rm -f "${GATEWAY_PID}"
        log_ok "Gateway stopped"
    elif is_port_listening "${GATEWAY_PORT}"; then
        local pid
        pid=$(find_gateway_by_port)
        if [[ -n "${pid}" ]]; then
            log_info "Stopping gateway on port ${GATEWAY_PORT} (PID: ${pid})..."
            kill "${pid}" 2>/dev/null || true
            sleep 1
            rm -f "${GATEWAY_PID}"
            log_ok "Gateway stopped"
        fi
    else
        log_warn "Gateway is not running"
    fi

    # The backend is managed externally; only the gateway process is stopped.
    log_info "Selected backend process is external to this launcher and is not stopped"
    echo ""
}

cmd_status() {
    local backend
    backend="$(normalize_backend "${2:-${BACKEND_DEFAULT}}")"
    if [[ -z "${backend}" ]]; then
        exit 1
    fi

    prepare_backend_env "${backend}" >/dev/null 2>&1 || true

    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  Oi Gateway + Agent Status (${backend})"
    echo "═══════════════════════════════════════════════════════════════"
    echo ""

    # Gateway status
    echo -n "Gateway (port ${GATEWAY_PORT}):     "
    if is_gateway_running; then
        local pid
        pid=$(get_gateway_pid)
        echo -e "${GREEN}RUNNING${NC} (PID: ${pid})"
    elif is_port_listening "${GATEWAY_PORT}"; then
        local pid
        pid=$(find_gateway_by_port)
        echo -e "${YELLOW}RUNNING${NC} (PID: ${pid:-unknown}, PID file stale)"
    else
        echo -e "${RED}STOPPED${NC}"
    fi

    # Backend status
    echo -n "Backend:                         "
    case "${backend}" in
        pi)
            if is_pi_available; then
                local pi_cmd
                pi_cmd=$(get_pi_cmd)
                echo -e "${GREEN}READY${NC} (pi command: ${pi_cmd})"
            else
                echo -e "${YELLOW}NOT FOUND${NC} (install pi to process text prompts)"
            fi
            ;;
        hermes)
            if [[ -n "${OI_HERMES_BASE_URL:-}" && -n "${OI_HERMES_API_KEY:-}" ]]; then
                echo -e "${GREEN}CONFIGURED${NC} (${OI_HERMES_BASE_URL})"
            else
                echo -e "${YELLOW}MISSING ENV${NC} (needs OI_HERMES_BASE_URL + OI_HERMES_API_KEY)"
            fi
            ;;
        openclaw)
            if [[ -n "${OI_OPENCLAW_TOKEN:-}" ]]; then
                echo -e "${GREEN}CONFIGURED${NC} (${OI_OPENCLAW_URL:-ws://127.0.0.1:18789})"
            else
                echo -e "${YELLOW}MISSING TOKEN${NC} (needs OI_OPENCLAW_TOKEN or OPENCLAW_GATEWAY_TOKEN)"
            fi
            ;;
    esac

    # Additional info
    echo ""
    if is_gateway_running || is_port_listening "${GATEWAY_PORT}"; then
        echo "  Gateway URL:  ws://localhost:${GATEWAY_PORT}/datp"
        echo "  REST API:     http://localhost:8788/api/health"
        echo "  Backend:      ${backend}"
        if [[ -f "${LOG_FILE}" ]]; then
            echo "  Log file:     ${LOG_FILE}"
        fi
    fi
    echo ""

    # Recent activity
    if [[ -f "${LOG_FILE}" ]]; then
        echo "  Recent gateway log:"
        tail -5 "${LOG_FILE}" 2>/dev/null | sed 's/^/    /' || true
        echo ""
    fi

    echo "═══════════════════════════════════════════════════════════════"
    echo ""
}

cmd_restart() {
    log_info "Restarting Oi Gateway..."
    echo ""
    cmd_stop
    sleep 1
    cmd_start start "${2:-${BACKEND_DEFAULT}}"
}

cmd_logs() {
    if [[ -f "${LOG_FILE}" ]]; then
        echo "═══════════════════════════════════════════════════════════════"
        echo "  Gateway Log (${LOG_FILE})"
        echo "═══════════════════════════════════════════════════════════════"
        echo ""
        tail -50 "${LOG_FILE}"
    else
        log_warn "No log file found at ${LOG_FILE}"
    fi
}

cmd_test() {
    local backend_target="${2:-${BACKEND_DEFAULT}}"
    local backend

    if [[ "${backend_target}" == "all" ]]; then
        backend="all"
    else
        backend="$(normalize_backend "${backend_target}")"
    fi

    if [[ -z "${backend}" ]]; then
        exit 1
    fi

    log_info "Running connectivity test..."
    echo ""

    log_info "Backend under test: ${backend}"

    if [[ "${backend}" == "all" ]]; then
        local any_failed=0
        local candidate
        for candidate in pi hermes openclaw; do
            log_info "Validating backend config: ${candidate}"
            if validate_backend_config "${candidate}" >/dev/null 2>&1; then
                log_ok "${candidate} backend config is valid"
            else
                log_warn "${candidate} backend config is not ready"
                any_failed=1
            fi
        done
        echo ""
        if [[ "${any_failed}" -ne 0 ]]; then
            return 1
        fi
        return 0
    fi

    if ! prepare_backend_env "${backend}"; then
        log_err "Missing required env for backend '${backend}'"
        case "${backend}" in
            hermes)
                log_err "Need OI_HERMES_BASE_URL and OI_HERMES_API_KEY"
                ;;
            openclaw)
                log_err "Need OI_OPENCLAW_TOKEN (or OPENCLAW_GATEWAY_TOKEN)"
                ;;
        esac
        exit 1
    fi

    if validate_backend_config "${backend}" >/dev/null 2>&1; then
        log_ok "Backend config is valid (${backend})"
    else
        log_warn "Backend config could not be validated (${backend})"
    fi

    # Check port
    if is_port_listening "${GATEWAY_PORT}"; then
        log_ok "Port ${GATEWAY_PORT} is listening"
    else
        log_err "Port ${GATEWAY_PORT} is NOT listening"
    fi

    # Check gateway endpoint (if port is open)
    if is_port_listening "${GATEWAY_PORT}"; then
        if command -v curl &>/dev/null; then
            if curl -sf "http://localhost:8788/api/health" &>/dev/null; then
                log_ok "Gateway API responding"
                curl -s "http://localhost:8788/api/health" | python3 -m json.tool 2>/dev/null | sed 's/^/  /' || true
            else
                log_warn "Gateway API not responding to /api/health"
            fi
        fi
    fi

    # Check WebSocket connectivity with Python
    if is_port_listening "${GATEWAY_PORT}"; then
        if "$(python_cmd)" -c "
import asyncio, websockets, json, sys
async def test():
    try:
        ws = await asyncio.wait_for(websockets.connect('ws://localhost:${GATEWAY_PORT}/datp'), timeout=2)
        hello = {'v':'datp','type':'hello','id':'test','device_id':'test-device','ts':'2026-01-01T00:00:00.000Z','payload':{'device_type':'test','protocol':'datp','firmware':'test','capabilities':{},'state':{}}}
        await ws.send(json.dumps(hello))
        await asyncio.wait_for(ws.recv(), timeout=2)
        print('Gateway accepts WebSocket connections: YES')
        await ws.close()
    except Exception as e:
        print(f'Gateway accepts WebSocket connections: NO ({e})')
        sys.exit(1)
asyncio.run(test())
" 2>/dev/null; then
            log_ok "WebSocket connectivity: OK"
        else
            log_warn "WebSocket connectivity: Failed (expected if gateway just started)"
        fi
    fi

    echo ""
}

cmd_help() {
    cat <<EOF
Oi Gateway + Agent Manager

Usage: $0 <command>

Commands:
    start [backend]      Start gateway with backend: pi, hermes, openclaw
    stop                 Stop gateway
    restart [backend]    Restart gateway with backend
    status [backend]     Show status of gateway and selected backend
    logs                 Show recent gateway logs
    test [backend|all]   Validate backend config and connectivity
    help                 Show this help

Examples:
    $0 start openclaw    # Start gateway against OpenClaw
    $0 start hermes      # Start gateway against Hermes
    $0 start pi          # Start gateway against local pi subprocess
    $0 status openclaw   # Check gateway + selected backend config
    $0 test openclaw     # Validate gateway + OpenClaw connectivity
    $0 stop              # Stop gateway

Configuration:
    Gateway runs on port ${GATEWAY_PORT}
    Logs written to ${LOG_FILE}
    PID file at ${GATEWAY_PID}
    Oi home directory: ${OI_HOME_DIR}

EOF
}

# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

case "${1:-help}" in
    start)   cmd_start "$@" ;;
    stop)    cmd_stop ;;
    restart) cmd_restart "$@" ;;
    status)  cmd_status "$@" ;;
    logs)    cmd_logs ;;
    test)    cmd_test "$@" ;;
    help|--help|-h) cmd_help ;;
    *)
        log_err "Unknown command: $1"
        echo ""
        cmd_help
        exit 1
        ;;
esac
