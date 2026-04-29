# oi_session_ui.py — pure helpers for session/command UI.
# MicroPython-compatible: keep dependencies minimal.

from pi_rpc_commands import COMMAND_BUILDERS

# Extended command set with tier-D and tier-P entries.
# Keep this list ≤ 12 so all items fit on-screen without scrolling.
COMMANDS = [
    # Tier D — direct
    ("abort", "abort", {}),
    ("retry", "abort_retry", {}),
    ("next model", "cycle_model", {}),
    ("next think", "cycle_thinking_level", {}),
    # Tier P — presets
    ("test: speak", "speak", {}),
    ("speak", "speak", {}),
    ("prompt OK", "prompt", {"message": "Reply with exactly: OK"}),
    ("prompt review", "prompt", {"message": "Review the code and suggest improvements."}),
    ("prompt explain", "prompt", {"message": "Explain what this does in one sentence."}),
    ("compact", "compact", {}),
    ("approve", "prompt", {"message": "Approval test: use bash to run `pwd`, then write to create `/tmp/oi-approval-test.txt`. If approvals enabled, ask before each tool call. Report completion."}),
]

_LOCAL_VERBS = {"voice", "speak"}
_RPC_VERB_ALIASES = {"status": "get_state"}


def command_is_local(idx):
    """True if the command at idx is handled on-device, not sent to the server."""
    _, verb, _ = COMMANDS[wrap_index(idx, len(COMMANDS))]
    return verb in _LOCAL_VERBS


def sessions_summary(state):
    """Return (active_session_id, sessions_list) from a /oi/state payload."""
    if not state:
        return None, []
    summary = state.get("sessions") or {}
    sessions = summary.get("sessions") or []
    if not isinstance(sessions, list):
        sessions = []
    return summary.get("active_session_id"), sessions


def selected_index_for_active(sessions, active_session_id):
    if not sessions:
        return 0
    for i, session in enumerate(sessions):
        if session.get("session_id") == active_session_id:
            return i
    return 0


def wrap_index(idx, count):
    if count <= 0:
        return 0
    return idx % count


def visible_window_start(highlighted, count, max_rows):
    """Return first visible row index for a menu window containing highlighted."""
    if count <= 0 or max_rows <= 0:
        return 0
    highlighted = wrap_index(highlighted, count)
    max_start = max(0, count - max_rows)
    if highlighted > max_start:
        return max_start
    return highlighted


def session_label(session):
    name = session.get("name") or session.get("session_id") or "?"
    return str(name)


def _age_label(age_s):
    try:
        age_s = int(age_s)
    except (TypeError, ValueError):
        return ""
    if age_s < 60:
        return "%ds" % age_s
    if age_s < 3600:
        return "%dm" % (age_s // 60)
    return "%dh" % (age_s // 3600)


def session_status(session):
    pending = session.get("pending_count") or 0
    status = session.get("status") or "?"
    if session.get("stale"):
        age = _age_label(session.get("last_seen_age_s"))
        status = "offline" + (" " + age if age else "")
    if pending:
        return "%s p:%s" % (status, pending)
    return str(status)


def command_count():
    return len(COMMANDS)


def command_label(idx):
    return COMMANDS[wrap_index(idx, len(COMMANDS))][0]


def command_payload(session_id, idx):
    label, verb, args = COMMANDS[wrap_index(idx, len(COMMANDS))]
    return {
        "session_id": session_id,
        "verb": verb,
        "args": dict(args),
        "request_id": "fw:%s:%s" % (session_id, label),
    }


def json_headers(token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def rpc_command_payload(session_id, idx):
    """Build a Pi RPC command dict from a command index."""
    label, verb, args = COMMANDS[wrap_index(idx, len(COMMANDS))]
    command = _RPC_VERB_ALIASES.get(verb, verb)
    if command in COMMAND_BUILDERS:
        return COMMAND_BUILDERS[command](command, **args)
    if verb == "voice":
        return None  # handled locally
    return {"type": verb}
