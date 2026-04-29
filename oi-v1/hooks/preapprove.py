#!/usr/bin/env python3
"""
Claude Code PreToolUse hook — route permission decisions to the oi desk device.

Install in settings.local.json:

  {
    "hooks": {
      "PreToolUse": [
        {
          "matcher": "Bash|Write|Edit",
          "hooks": [
            {"type": "command",
             "command": "python3 /path/to/oi/hooks/preapprove.py"}
          ]
        }
      ]
    }
  }

On stdin, Claude Code sends:
  {
    "session_id": "...",
    "tool_name": "Bash",
    "tool_input": {"command": "...", "description": "..."},
    "tool_use_id": "toolu_...",
    "cwd": "...",
    "permission_mode": "default"
  }

We post a question to the oi device, wait up to HOOK_TIMEOUT_S for a button
press, and emit one of:

  - approve:  {"permissionDecision": "allow",  "permissionDecisionReason": "..."}
  - deny:     {"permissionDecision": "deny",   "permissionDecisionReason": "..."}
  - notes:    {"permissionDecision": "ask",    "permissionDecisionReason": "..."} (fall through to CLI so user can add notes)
  - timeout:  {"permissionDecision": "ask",    "permissionDecisionReason": "oi timeout"} (fall through)

If the oi server is unreachable or anything fails, we ALLOW the tool by
default (exit 0 with no stdout) so the hook never blocks a session.

Disable the hook at any time by removing the block from settings.local.json.
"""

from __future__ import annotations

import json
import os
import sys
import traceback

# Add the agent helper to sys.path so we can import oi. Default to this repo;
# allow OI_AGENT_DIR for deployments that install the hook elsewhere.
AGENT_DIR = os.environ.get(
    "OI_AGENT_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "agent")),
)
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

HOOK_TIMEOUT_S = 60.0

# Bypass: if this env var is set, hook returns "allow" immediately without
# routing to the device. Useful for scripted/autonomous sessions.
BYPASS_ENV = "OI_BYPASS"


def _fail_open(reason: str) -> None:
    """Emit nothing (implicit allow). Log the reason to stderr for transcript."""
    print(f"[oi-hook] fail-open: {reason}", file=sys.stderr)
    sys.exit(0)


def _emit(decision: str, reason: str) -> None:
    """Write the hook response JSON and exit 0."""
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()
    sys.exit(0)


def _hint_for(tool_name: str, tool_input: dict) -> str:
    """Compose a short (≤150 char) body describing the tool call."""
    if tool_name == "Bash":
        cmd = str(tool_input.get("command") or "").strip()
        return cmd[:150]
    if tool_name == "Write":
        path = tool_input.get("file_path") or "?"
        size = len(str(tool_input.get("content") or ""))
        return f"write {path} ({size}b)"[:150]
    if tool_name == "Edit":
        path = tool_input.get("file_path") or "?"
        return f"edit {path}"[:150]
    # Generic fallback — stringify the input, trimmed
    return (tool_name + ": " + json.dumps(tool_input))[:150]


def main() -> None:
    try:
        payload = sys.stdin.read()
        if not payload.strip():
            _fail_open("empty stdin")

        try:
            data = json.loads(payload)
        except Exception as e:
            _fail_open(f"bad json: {e}")

        if os.environ.get(BYPASS_ENV):
            _fail_open(f"{BYPASS_ENV} set")

        tool_name = data.get("tool_name") or "?"
        tool_input = data.get("tool_input") or {}
        session_id = data.get("session_id")
        tool_use_id = data.get("tool_use_id")
        cwd = data.get("cwd") or ""

        hint = _hint_for(tool_name, tool_input)

        # Import here so we fail-open if the module is broken, rather than
        # crashing the hook.
        try:
            import oi  # type: ignore
        except Exception as e:
            _fail_open(f"oi import failed: {e}")

        try:
            if session_id:
                oi.register_session(
                    session_id=session_id,
                    name=(os.path.basename(cwd) if cwd else session_id[:8]),
                    cwd=cwd,
                    kind="pi",
                    status="needs_approval",
                    summary=tool_name,
                )
                pick = oi.approve_session(
                    session_id,
                    tool_name,
                    hint,
                    tool_use_id=tool_use_id,
                    timeout=HOOK_TIMEOUT_S,
                )
            else:
                pick = oi.approve(tool_name, hint, timeout=HOOK_TIMEOUT_S)
        except Exception as e:
            _fail_open(f"oi approval failed: {e}")

        if pick == "approve":
            _emit("allow", "approved via oi")
        elif pick == "deny":
            _emit("deny", "denied via oi")
        elif pick == "notes":
            # Fall through to the normal CLI prompt so user can add context
            _emit("ask", "oi: notes — fall through to CLI")
        else:
            # None (timeout) or unrecognised — fall through to CLI
            _emit("ask", f"oi: {pick or 'timeout'}")

    except SystemExit:
        raise
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        _fail_open(f"unexpected: {e}")


if __name__ == "__main__":
    main()
