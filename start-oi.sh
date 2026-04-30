#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY_DIR="${SCRIPT_DIR}/src/oi-gateway"
DASHBOARD_DIR="${SCRIPT_DIR}/src/oi-dashboard"
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
GATEWAY_PID_FILE="${STATE_DIR}/gateway.pid"
DASHBOARD_PID_FILE="${STATE_DIR}/dashboard.pid"
GATEWAY_LOG_FILE="${LOG_DIR}/gateway.log"
DASHBOARD_LOG_FILE="${LOG_DIR}/dashboard.log"
GATEWAY_PORT="${OI_GATEWAY_PORT:-8787}"
API_PORT="${OI_GATEWAY_API_PORT:-8788}"
DASHBOARD_PORT="${OI_DASHBOARD_PORT:-8789}"
DASHBOARD_HOST="${OI_DASHBOARD_HOST:-0.0.0.0}"
DASHBOARD_API_URL="${OI_DASHBOARD_API_URL:-http://localhost:${API_PORT}}"

mkdir -p "${STATE_DIR}" "${LOG_DIR}"

is_running() {
  local pid_file="$1"
  [[ -f "${pid_file}" ]] || return 1
  local pid
  pid="$(cat "${pid_file}")"
  kill -0 "${pid}" 2>/dev/null
}

start_gateway() {
  local backend="$1"

  if is_running "${GATEWAY_PID_FILE}"; then
    echo "Gateway already running (PID $(cat "${GATEWAY_PID_FILE}"))"
    return 0
  fi

  echo "Starting oi-gateway (backend=${backend})"

  cd "${GATEWAY_DIR}"
  nohup env \
    OI_HOME="${OI_HOME_DIR}" \
    OI_AGENT_BACKEND="${backend}" \
    PYTHONPATH="${GATEWAY_DIR}/src" \
    "${PYTHON}" -m gateway_app >> "${GATEWAY_LOG_FILE}" 2>&1 &

  echo $! > "${GATEWAY_PID_FILE}"
  sleep 1
  if is_running "${GATEWAY_PID_FILE}"; then
    echo "Gateway started (PID $(cat "${GATEWAY_PID_FILE}"))"
    return 0
  fi

  echo "Failed to start gateway. See ${GATEWAY_LOG_FILE}" >&2
  return 1
}

start_dashboard() {
  if is_running "${DASHBOARD_PID_FILE}"; then
    echo "Dashboard already running (PID $(cat "${DASHBOARD_PID_FILE}"))"
    return 0
  fi

  echo "Starting oi-dashboard (${DASHBOARD_API_URL} -> http://${DASHBOARD_HOST}:${DASHBOARD_PORT})"

  cd "${DASHBOARD_DIR}"
  nohup env \
    OI_HOME="${OI_HOME_DIR}" \
    PYTHONPATH="${DASHBOARD_DIR}/src" \
    "${PYTHON}" -m oi_dashboard.cli \
      --api-url "${DASHBOARD_API_URL}" \
      --host "${DASHBOARD_HOST}" \
      --port "${DASHBOARD_PORT}" >> "${DASHBOARD_LOG_FILE}" 2>&1 &

  echo $! > "${DASHBOARD_PID_FILE}"
  sleep 1
  if is_running "${DASHBOARD_PID_FILE}"; then
    echo "Dashboard started (PID $(cat "${DASHBOARD_PID_FILE}"))"
    return 0
  fi

  echo "Failed to start dashboard. See ${DASHBOARD_LOG_FILE}" >&2
  return 1
}

start() {
  local backend="${2:-${OI_AGENT_BACKEND:-pi}}"
  local gateway_was_running=false

  if is_running "${GATEWAY_PID_FILE}"; then
    gateway_was_running=true
  fi

  start_gateway "${backend}" || exit 1

  if ! start_dashboard; then
    if [[ "${gateway_was_running}" == "false" ]]; then
      stop_process "gateway" "${GATEWAY_PID_FILE}"
    fi
    exit 1
  fi
}

stop_process() {
  local name="$1"
  local pid_file="$2"

  if ! is_running "${pid_file}"; then
    echo "${name} is not running"
    rm -f "${pid_file}"
    return 0
  fi

  local pid
  pid="$(cat "${pid_file}")"
  kill "${pid}" 2>/dev/null || true
  sleep 1
  kill -9 "${pid}" 2>/dev/null || true
  rm -f "${pid_file}"
  echo "Stopped ${name}"
}

stop() {
  stop_process "dashboard" "${DASHBOARD_PID_FILE}"
  stop_process "gateway" "${GATEWAY_PID_FILE}"
}

status_line() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  local port="$4"

  if is_running "${pid_file}"; then
    echo "${name}: RUNNING (PID $(cat "${pid_file}"))"
  else
    echo "${name}: STOPPED"
  fi
  echo "  Log: ${log_file}"
  echo "  Port: ${port}"
}

status() {
  status_line "Gateway" "${GATEWAY_PID_FILE}" "${GATEWAY_LOG_FILE}" "${GATEWAY_PORT} / API ${API_PORT}"
  status_line "Dashboard" "${DASHBOARD_PID_FILE}" "${DASHBOARD_LOG_FILE}" "${DASHBOARD_PORT}"
  echo "  URL: http://${DASHBOARD_HOST}:${DASHBOARD_PORT}"
}

logs() {
  echo "== gateway log =="
  [[ -f "${GATEWAY_LOG_FILE}" ]] && tail -50 "${GATEWAY_LOG_FILE}" || echo "No gateway logs yet"
  echo
  echo "== dashboard log =="
  [[ -f "${DASHBOARD_LOG_FILE}" ]] && tail -50 "${DASHBOARD_LOG_FILE}" || echo "No dashboard logs yet"
}

test_cmd() {
  local gateway_test_url="${OI_GATEWAY_API_TEST_URL:-http://127.0.0.1:${API_PORT}}"
  local dashboard_test_url="${OI_DASHBOARD_TEST_URL:-http://127.0.0.1:${DASHBOARD_PORT}}"

  if curl -sf "${gateway_test_url}/api/health" >/dev/null 2>&1; then
    echo "Gateway health check OK"
  else
    echo "Gateway health check failed"
    return 1
  fi

  if curl -sf "${dashboard_test_url}/api/health" >/dev/null 2>&1; then
    echo "Dashboard health check OK"
  else
    echo "Dashboard health check failed"
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
    echo "Environment: OI_DASHBOARD_HOST (default 0.0.0.0), OI_DASHBOARD_PORT (default 8789), OI_DASHBOARD_API_URL"
    echo "             OI_GATEWAY_API_TEST_URL, OI_DASHBOARD_TEST_URL"
    ;;
esac
