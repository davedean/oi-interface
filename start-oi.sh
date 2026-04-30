#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY_DIR="${SCRIPT_DIR}/src/oi-gateway"
VENV_PY="${SCRIPT_DIR}/.venv/bin/python"
PYTHON="${VENV_PY}"
[[ -x "${PYTHON}" ]] || PYTHON="python3"

resolve_oi_home() {
  if [[ -n "${OI_HOME:-}" ]]; then echo "${OI_HOME}";
  elif [[ -n "${XDG_CONFIG_HOME:-}" ]]; then echo "${XDG_CONFIG_HOME}/oi";
  else echo "${HOME}/.oi"; fi
}

OI_HOME_DIR="$(resolve_oi_home)"
STATE_DIR="${OI_HOME_DIR}/state/oi-gateway"
LOG_DIR="${OI_HOME_DIR}/logs/oi-gateway"
PID_FILE="${STATE_DIR}/gateway.pid"
LOG_FILE="${LOG_DIR}/gateway.log"
PORT="${OI_GATEWAY_PORT:-8787}"

mkdir -p "${STATE_DIR}" "${LOG_DIR}"

is_running() {
  [[ -f "${PID_FILE}" ]] || return 1
  local pid
  pid="$(cat "${PID_FILE}")"
  kill -0 "${pid}" 2>/dev/null
}

start() {
  if is_running; then
    echo "Gateway already running (PID $(cat "${PID_FILE}"))"
    return 0
  fi

  local backend="${2:-${OI_AGENT_BACKEND:-pi}}"
  echo "Starting oi-gateway (backend=${backend})"

  cd "${GATEWAY_DIR}"
  nohup env \
    OI_HOME="${OI_HOME_DIR}" \
    OI_AGENT_BACKEND="${backend}" \
    PYTHONPATH="${GATEWAY_DIR}/src" \
    "${PYTHON}" -m gateway_app >> "${LOG_FILE}" 2>&1 &

  echo $! > "${PID_FILE}"
  sleep 1
  if is_running; then
    echo "Started (PID $(cat "${PID_FILE}"))"
  else
    echo "Failed to start. See ${LOG_FILE}" >&2
    exit 1
  fi
}

stop() {
  if ! is_running; then
    echo "Gateway is not running"
    rm -f "${PID_FILE}"
    return 0
  fi
  local pid
  pid="$(cat "${PID_FILE}")"
  kill "${pid}" 2>/dev/null || true
  sleep 1
  kill -9 "${pid}" 2>/dev/null || true
  rm -f "${PID_FILE}"
  echo "Stopped"
}

status() {
  if is_running; then
    echo "Gateway: RUNNING (PID $(cat "${PID_FILE}"))"
  else
    echo "Gateway: STOPPED"
  fi
  echo "Log: ${LOG_FILE}"
  echo "Port: ${PORT}"
}

logs() {
  [[ -f "${LOG_FILE}" ]] && tail -50 "${LOG_FILE}" || echo "No logs yet"
}

test_cmd() {
  if curl -sf "http://localhost:8788/api/health" >/dev/null 2>&1; then
    echo "Health check OK"
  else
    echo "Health check failed"
    return 1
  fi
}

case "${1:-help}" in
  start) start "$@" ;;
  stop) stop ;;
  restart) stop; start "start" "${2:-}" ;;
  status) status ;;
  logs) logs ;;
  test) test_cmd ;;
  *)
    echo "Usage: $0 {start [backend]|stop|restart [backend]|status|logs|test}"
    ;;
esac
