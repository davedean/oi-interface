"""
oi — agent-side helper for interacting with the desk device.

Usage from Python:

    from projects.oi.agent import oi

    # Display a message, block until the user presses BtnA (ack) or BtnB (dismiss).
    result = oi.say("briefing done, coffee's ready")
    # result is "ok" on BtnA, "skip" on BtnB, None on timeout.

    # Ask a question with options, block until the user picks one.
    pick = oi.ask(
        "plan the evening?",
        body="3 options, pick one",
        options=[("plan",  "plan"),
                 ("chill", "chill"),
                 ("stop",  "stop")],
    )
    # pick is one of "plan" / "chill" / "stop", or None on timeout.

    # See recent pings.
    for p in oi.recent_pings():
        print(p)

    # Block until the user pings.
    oi.wait_for_ping(timeout=600)

The helper is stateless and talks to the running oi server on localhost
(default http://127.0.0.1:8842, override with OI_SERVER_URL). It polls the
server for answers; it does not hold any local state.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

SERVER_URL = os.environ.get("OI_SERVER_URL", "http://127.0.0.1:8842")
POLL_INTERVAL_S = 1.0


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only — no requests dep)
# ---------------------------------------------------------------------------

def _headers(extra: dict | None = None) -> dict:
    headers = dict(extra or {})
    token = os.environ.get("OI_API_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def _get(path: str, timeout: float = 4.0) -> dict:
    req = urllib.request.Request(SERVER_URL + path, headers=_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(path: str, payload: dict, timeout: float = 4.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SERVER_URL + path,
        data=data,
        headers=_headers({"Content-Type": "application/json"}),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Option normalisation
# ---------------------------------------------------------------------------

def _normalise_options(options) -> list:
    """
    Accept options in any of these shapes:
      - None / [] → default [{"label": "ok", "value": "ok"}]
      - list of strings → label == value
      - list of (label, value) tuples
      - list of {"label": ..., "value": ...} dicts (passed through)
    """
    if not options:
        return [{"label": "ok", "value": "ok"}]
    out = []
    for o in options:
        if isinstance(o, str):
            out.append({"label": o, "value": o})
        elif isinstance(o, tuple) and len(o) == 2:
            out.append({"label": str(o[0]), "value": str(o[1])})
        elif isinstance(o, dict) and "label" in o and "value" in o:
            out.append({"label": str(o["label"]), "value": str(o["value"])})
        else:
            raise ValueError(f"bad option: {o!r}")
    return out


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

def ask(
    title: str,
    body: str = "",
    options: Optional[Iterable] = None,
    timeout: float = 1800.0,
    clear_on_timeout: bool = False,
) -> Optional[str]:
    """
    Post a question to the device and block until the user answers or timeout.

    Returns the picked option's `value`, or None on timeout.

    On timeout, the question STAYS on the device by default — the agent has
    given up waiting but the user can still see and respond when they look.
    The eventual answer lands in /oi/answers; the agent can poll it later.
    Pass `clear_on_timeout=True` to force the device back to idle on timeout.
    """
    opts = _normalise_options(options)
    qid = f"q-{int(time.time() * 1000)}"
    _post("/oi/state", {
        "id": qid,
        "title": title,
        "body": body or "",
        "options": opts,
    })

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            recent = _get("/oi/answers")
        except urllib.error.URLError:
            time.sleep(POLL_INTERVAL_S)
            continue
        for a in recent.get("answers", []):
            if a.get("id") == qid:
                return a.get("value")
        time.sleep(POLL_INTERVAL_S)

    if clear_on_timeout:
        try:
            _post("/oi/state", {"id": None})
        except Exception:
            pass
    return None


def say(text: str, title: str = "", timeout: float = 1800.0,
        clear_on_timeout: bool = False) -> Optional[str]:
    """
    Display a message on the device. Block until user acks (BtnA) or
    dismisses (BtnB), or timeout.

    Default timeout is 30 min and the message stays on screen if the agent
    gives up — the user can still respond later (answer lands in /oi/answers).

    If `title` is empty, the first line of `text` becomes the title.
    Returns "ok" (BtnA), "skip" (BtnB), or None (timeout).
    """
    if not title:
        # First ~18 chars (fits the large font title) become the title.
        title = text.strip().split("\n", 1)[0][:18] or "oi"
        body = text
    else:
        body = text
    return ask(
        title=title,
        body=body,
        options=[("ok", "ok"), ("skip", "skip")],
        timeout=timeout,
        clear_on_timeout=clear_on_timeout,
    )


def clear() -> None:
    """Manually return the device to idle."""
    _post("/oi/state", {"id": None})


# ---------------------------------------------------------------------------
# Session-aware APIs
# ---------------------------------------------------------------------------

def register_session(session_id: str, name: str = "", cwd: str = "", kind: str = "pi",
                     status: str = "idle", summary: str | None = None,
                     model: str | None = None) -> dict:
    payload = {
        "session_id": session_id,
        "name": name or session_id[:8],
        "cwd": cwd or None,
        "kind": kind,
        "status": status,
    }
    if summary is not None:
        payload["summary"] = summary
    if model is not None:
        payload["model"] = model
    return _post("/oi/sessions/upsert", payload).get("session", {})


def list_sessions() -> dict:
    return _get("/oi/sessions")


def session_stats() -> dict:
    return _get("/oi/sessions/stats")


def activate_session(session_id: str | None) -> dict | None:
    return _post("/oi/sessions/active", {"session_id": session_id}).get("session")


def ask_session(session_id: str, title: str, body: str = "", options: Optional[Iterable] = None,
                kind: str = "question", tool_use_id: str | None = None,
                timeout: float = 1800.0, cancel_on_timeout: bool = False) -> Optional[str]:
    opts = _normalise_options(options)
    prompt = _post("/oi/prompts", {
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "kind": kind,
        "title": title,
        "body": body or "",
        "options": opts,
    }).get("prompt", {})
    prompt_id = prompt.get("prompt_id")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            recent = _get("/oi/answers")
        except urllib.error.URLError:
            time.sleep(POLL_INTERVAL_S)
            continue
        for a in recent.get("answers", []):
            if a.get("id") == prompt_id or a.get("prompt_id") == prompt_id:
                return a.get("value")
        time.sleep(POLL_INTERVAL_S)
    if cancel_on_timeout and prompt_id:
        try:
            cancel_prompt(prompt_id)
        except Exception:
            pass
    return None


def list_session_prompts(session_id: str | None = None, status: str | None = None,
                         limit: int | None = None) -> list:
    params = {}
    if session_id:
        params["session_id"] = session_id
    if status:
        params["status"] = status
    if limit is not None:
        params["limit"] = int(limit)
    query = urllib.parse.urlencode(params)
    path = "/oi/prompts" + (("?" + query) if query else "")
    return _get(path).get("prompts", [])


def cancel_prompt(prompt_id: str) -> dict:
    return _post(f"/oi/prompts/{prompt_id}/cancel", {}).get("prompt", {})


def count_pending_prompts(session_id: str | None = None) -> int:
    return len(list_session_prompts(session_id=session_id, status="pending"))


def cancel_pending_prompts(session_id: str | None = None) -> int:
    payload = {"session_id": session_id} if session_id else {}
    try:
        return int(_post("/oi/prompts/cancel", payload).get("cancelled") or 0)
    except urllib.error.HTTPError as e:
        # Backward compatibility with older servers lacking bulk endpoint.
        if e.code != 404:
            raise
        count = 0
        for prompt in list_session_prompts(session_id=session_id, status="pending"):
            prompt_id = prompt.get("prompt_id")
            if isinstance(prompt_id, str) and prompt_id:
                cancel_prompt(prompt_id)
                count += 1
        return count


def approve_session(session_id: str, tool: str, hint: str = "", tool_use_id: str | None = None,
                    timeout: float = 60.0) -> str | None:
    title = ("approve: " + tool)[:15]
    return ask_session(
        session_id=session_id,
        tool_use_id=tool_use_id,
        kind="approval",
        title=title,
        body=hint,
        options=["approve", "notes", "deny"],
        timeout=timeout,
        cancel_on_timeout=True,
    )


def _iso_after(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=float(seconds))).astimezone().isoformat()


def send_command(session_id: str, verb: str, args: dict | None = None,
                 request_id: str | None = None,
                 expires_in: float | None = None,
                 expires_at: str | None = None) -> dict:
    if expires_at is not None and expires_in is not None:
        raise ValueError("pass either expires_at or expires_in, not both")
    payload = {
        "session_id": session_id,
        "verb": verb,
        "args": args or {},
    }
    if request_id is not None:
        payload["request_id"] = request_id
    if expires_at is not None:
        payload["expires_at"] = expires_at
    elif expires_in is not None:
        payload["expires_at"] = _iso_after(expires_in)
    return _post("/oi/commands", payload).get("command", {})


def poll_commands(session_id: str, after_seq: int = 0, status: str = "queued") -> list:
    query = urllib.parse.urlencode({"session_id": session_id, "after_seq": after_seq, "status": status})
    return _get("/oi/commands?" + query).get("commands", [])


def list_commands(session_id: str | None = None, status: str = "queued", after_seq: int = 0,
                  limit: int | None = None) -> list:
    params = {"after_seq": after_seq, "status": status}
    if session_id:
        params["session_id"] = session_id
    if limit is not None:
        params["limit"] = int(limit)
    query = urllib.parse.urlencode(params)
    return _get("/oi/commands?" + query).get("commands", [])


def ack_command(command_id: str, result=None) -> dict:
    return _post(f"/oi/commands/{command_id}/ack", {"result": result}).get("command", {})


def fail_command(command_id: str, error) -> dict:
    return _post(f"/oi/commands/{command_id}/fail", {"error": str(error)}).get("command", {})


def cancel_command(command_id: str, reason: str = "operator") -> dict:
    return _post(f"/oi/commands/{command_id}/cancel", {"reason": reason}).get("command", {})


def count_queued_commands(session_id: str | None = None) -> int:
    return len(list_commands(session_id=session_id, status="queued", after_seq=0))


def cancel_queued_commands(session_id: str | None = None, reason: str = "operator bulk cancel") -> int:
    payload = {"reason": reason}
    if session_id:
        payload["session_id"] = session_id
    try:
        return int(_post("/oi/commands/cancel", payload).get("cancelled") or 0)
    except urllib.error.HTTPError as e:
        # Backward compatibility with older servers lacking bulk endpoint.
        if e.code != 404:
            raise
        count = 0
        for command in list_commands(session_id=session_id, status="queued", after_seq=0):
            command_id = command.get("command_id")
            if isinstance(command_id, str) and command_id:
                cancel_command(command_id, reason=reason)
                count += 1
        return count


def cleanup_session(session_id: str | None = None, reason: str = "operator cleanup") -> dict:
    payload = {"reason": reason}
    if session_id:
        payload["session_id"] = session_id
    try:
        result = _post("/oi/sessions/cleanup", payload)
        return {
            "cancelled_prompts": int(result.get("cancelled_prompts") or 0),
            "cancelled_commands": int(result.get("cancelled_commands") or 0),
        }
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        prompts = cancel_pending_prompts(session_id=session_id)
        commands = cancel_queued_commands(session_id=session_id, reason=reason)
        return {"cancelled_prompts": prompts, "cancelled_commands": commands}


def speak(text: str) -> dict:
    """Queue *text* for TTS playback on the device. Returns {"ok": True, "speak_seq": N}."""
    return _post("/oi/speak", {"text": text})


# ---------------------------------------------------------------------------
# Ping helpers
# ---------------------------------------------------------------------------

def recent_pings(n: int = 20, strict: bool = False) -> list:
    """Return list of recent ping records (most recent last)."""
    try:
        return _get("/oi/pings").get("pings", [])[-n:]
    except Exception:
        if strict:
            raise
        return []


def wait_for_ping(timeout: float = 600.0) -> Optional[dict]:
    """
    Block until a new ping arrives from the device. Returns the ping record,
    or None on timeout.

    "New" is defined relative to the most recent ping seen when this call
    started.
    """
    baseline = recent_pings()
    last_seq = _max_seq(baseline)
    last_ts = baseline[-1].get("ts") if baseline else None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pings = recent_pings()
        for p in pings:
            seq = p.get("seq")
            if isinstance(seq, int):
                if last_seq is None or seq > last_seq:
                    return p
            elif last_seq is None and (last_ts is None or p.get("ts", "") > last_ts):
                return p
        time.sleep(POLL_INTERVAL_S)
    return None


def _max_seq(records: list) -> int | None:
    seqs = [r.get("seq") for r in records if isinstance(r.get("seq"), int)]
    return max(seqs) if seqs else None


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

def snapshot(
    running: int | None = None,
    waiting: int | None = None,
    msg: str | None = None,
    entries: list[str] | None = None,
    tokens_today: int | None = None,
    **extras,
) -> dict:
    """
    POST an ambient dashboard snapshot to the device.

    All args optional — only non-None fields are sent. The server adds `ts`.
    Returns the server's stored snapshot.
    """
    payload: dict = {}
    if running is not None:
        payload["running"] = running
    if waiting is not None:
        payload["waiting"] = waiting
    if msg is not None:
        payload["msg"] = msg
    if entries is not None:
        payload["entries"] = list(entries)
    if tokens_today is not None:
        payload["tokens_today"] = tokens_today
    payload.update(extras)
    return _post("/oi/snapshot", payload).get("snapshot", {})


def clear_snapshot() -> None:
    """Remove the ambient snapshot from the device (returns it to idle)."""
    _post("/oi/snapshot", {"clear": True})


# ---------------------------------------------------------------------------
# Control helpers (brightness / mute / chirp)
# ---------------------------------------------------------------------------

def chirp(kind: str = "good") -> dict:
    """Play a chirp on the device. kind = 'good' (ascending) or 'bad' (descending)."""
    return _post("/oi/control", {"chirp": kind})


def set_brightness(pct: int) -> dict:
    """Deprecated: device brightness is now local-only; server no longer applies it."""
    raise RuntimeError("brightness is controlled on the device settings screen")


def set_mute(muted: bool = True) -> dict:
    """Deprecated: device volume is now local-only; server no longer applies it."""
    raise RuntimeError("volume is controlled on the device settings screen")


# ---------------------------------------------------------------------------
# Status helper
# ---------------------------------------------------------------------------

def status(n: int = 5) -> dict:
    """Return health, current question, snapshot/control/device state, session stats, and recent pings."""
    health = _get("/oi/health")
    state = _get("/oi/state")
    question = None
    if state.get("id") is not None:
        question = {
            "id": state.get("id"),
            "title": state.get("title"),
            "body": state.get("body"),
            "options": state.get("options") or [],
            "ts": state.get("ts"),
        }
    pings = _get("/oi/pings").get("pings", [])[-n:]
    try:
        sessions = _get("/oi/sessions")
    except urllib.error.HTTPError:
        sessions = {"sessions": [], "active_session_id": None}
    try:
        stats = session_stats()
    except urllib.error.HTTPError:
        stats = None
    return {
        "health": health,
        "question": question,
        "snapshot": state.get("snapshot"),
        "control": state.get("control"),
        "device": state.get("device"),
        "sessions": sessions,
        "session_stats": stats,
        "pings": pings,
    }


def healthcheck(max_oldest_prompt_s: int = 300,
                max_oldest_command_s: int = 300,
                max_stale_sessions: int | None = None) -> dict:
    """Return machine-readable queue/session health with pass/fail reason list."""
    data = status(n=1)
    stats = data.get("session_stats") or {}
    reasons = []

    try:
        op = stats.get("oldest_pending_prompt_age_s")
        if op is not None and int(op) > int(max_oldest_prompt_s):
            reasons.append(f"oldest pending prompt {op}s > {max_oldest_prompt_s}s")
    except Exception:
        pass

    try:
        oc = stats.get("oldest_queued_command_age_s")
        if oc is not None and int(oc) > int(max_oldest_command_s):
            reasons.append(f"oldest queued command {oc}s > {max_oldest_command_s}s")
    except Exception:
        pass

    if max_stale_sessions is not None:
        try:
            stale = int(stats.get("stale_session_count") or 0)
            if stale > int(max_stale_sessions):
                reasons.append(f"stale sessions {stale} > {max_stale_sessions}")
        except Exception:
            pass

    return {
        "ok": len(reasons) == 0,
        "reasons": reasons,
        "stats": stats,
    }


def format_overview(data: dict) -> str:
    """Render a concise human-readable status overview."""
    lines = []
    health = data.get("health") or {}
    lines.append("service: " + ("ok" if health.get("ok") else "down"))

    question = data.get("question")
    if question:
        title = question.get("title") or ""
        lines.append("question: %s %s" % (question.get("id") or "?", title))
    else:
        lines.append("question: none")

    device = data.get("device") or {}
    if device:
        lines.append(
            "device: vol=%s mute=%s pace=%s" % (
                device.get("volume"),
                device.get("mute"),
                device.get("response_pace_hint"),
            )
        )

    sessions = (data.get("sessions") or {}).get("sessions") or []
    active_id = (data.get("sessions") or {}).get("active_session_id")
    active = next((s for s in sessions if s.get("session_id") == active_id), None)
    if active:
        lines.append("active: %s (%s)" % (active.get("name") or active_id, active.get("status") or "?"))

    stats = data.get("session_stats") or {}
    if stats:
        oldest_prompt = stats.get("oldest_pending_prompt_age_s")
        oldest_cmd = stats.get("oldest_queued_command_age_s")
        lines.append(
            "queues: prompts=%s commands=%s sessions=%s stale=%s oldest_prompt=%ss oldest_cmd=%ss" % (
                (stats.get("prompts") or {}).get("total"),
                (stats.get("commands") or {}).get("total"),
                stats.get("session_count"),
                stats.get("stale_session_count"),
                oldest_prompt,
                oldest_cmd,
            )
        )
        try:
            op = int(oldest_prompt) if oldest_prompt is not None else 0
            oc = int(oldest_cmd) if oldest_cmd is not None else 0
            if op >= 300 or oc >= 300:
                lines.append("warning: queue age high (oldest prompt/cmd >= 300s)")
        except Exception:
            pass

    pings = data.get("pings") or []
    if pings:
        lines.append("last ping: seq=%s ts=%s" % (pings[-1].get("seq"), pings[-1].get("ts")))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Approve convenience wrapper
# ---------------------------------------------------------------------------

def approve(tool: str, hint: str = "", timeout: float = 60.0,
            clear_on_timeout: bool = True) -> str | None:
    """
    Ask the user to approve/deny a tool call.

    title = "approve: {tool}" trimmed to 15 chars.
    options = ["approve", "notes", "deny"].
    Returns the picked string, or None on timeout.

    Defaults differ from say/ask: short timeout (60s) because permission
    decisions block tool execution, and clear_on_timeout=True because falling
    through to the CLI prompt makes the device prompt stale.
    """
    title = ("approve: " + tool)[:15]
    return ask(
        title=title,
        body=hint,
        options=["approve", "notes", "deny"],
        timeout=timeout,
        clear_on_timeout=clear_on_timeout,
    )


# ---------------------------------------------------------------------------
# CLI entrypoint — so agents / shells can just run this file.
# ---------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="oi", description="oi desk-device helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_say = sub.add_parser("say", help="display a message and wait for ack")
    p_say.add_argument("text")
    p_say.add_argument("--title", default="")
    p_say.add_argument("--timeout", type=float, default=600.0)

    p_ask = sub.add_parser("ask", help="ask a multi-choice question")
    p_ask.add_argument("title")
    p_ask.add_argument("--body", default="")
    p_ask.add_argument("-o", "--option", action="append", default=[],
                       help="option label (repeat for each). label==value.")
    p_ask.add_argument("--timeout", type=float, default=600.0)

    p_pings = sub.add_parser("pings", help="show recent pings")
    p_pings.add_argument("-n", type=int, default=20)

    p_status = sub.add_parser("status", help="show server/device status")
    p_status.add_argument("-n", type=int, default=5, help="recent ping count")

    p_overview = sub.add_parser("overview", help="show concise human-readable status")
    p_overview.add_argument("-n", type=int, default=1, help="recent ping count to inspect")

    p_healthcheck = sub.add_parser("healthcheck", help="check queue/session health thresholds")
    p_healthcheck.add_argument("--max-oldest-prompt", type=int, default=300)
    p_healthcheck.add_argument("--max-oldest-command", type=int, default=300)
    p_healthcheck.add_argument("--max-stale-sessions", type=int, default=None)

    p_sessions = sub.add_parser("sessions", help="list registered pi sessions")
    p_session_stats = sub.add_parser("session-stats", help="show session/prompt/command counters")

    p_prompts = sub.add_parser("prompts", help="list prompts")
    p_prompts.add_argument("--session-id", default=None)
    p_prompts.add_argument("--status", default=None)
    p_prompts.add_argument("--limit", type=int, default=None)

    p_cancel_prompts = sub.add_parser("cancel-prompts", help="cancel pending prompts")
    p_cancel_prompts.add_argument("--session-id", default=None)
    p_cancel_prompts.add_argument("--dry-run", action="store_true", help="show count only")

    p_commands = sub.add_parser("commands", help="list queued/acked/failed commands")
    p_commands.add_argument("--session-id", default=None)
    p_commands.add_argument("--status", default="queued")
    p_commands.add_argument("--after-seq", type=int, default=0)
    p_commands.add_argument("--limit", type=int, default=None)

    p_cancel_command = sub.add_parser("cancel-command", help="cancel one command by id")
    p_cancel_command.add_argument("command_id")
    p_cancel_command.add_argument("--reason", default="operator")

    p_cancel_commands = sub.add_parser("cancel-commands", help="cancel queued commands")
    p_cancel_commands.add_argument("--session-id", default=None)
    p_cancel_commands.add_argument("--reason", default="operator bulk cancel")
    p_cancel_commands.add_argument("--dry-run", action="store_true", help="show count only")

    p_cleanup = sub.add_parser("cleanup-session", help="cancel pending prompts and queued commands")
    p_cleanup.add_argument("--session-id", default=None)
    p_cleanup.add_argument("--reason", default="operator cleanup")
    p_cleanup.add_argument("--dry-run", action="store_true", help="show counts only")

    p_activate = sub.add_parser("activate-session", help="set active device session")
    p_activate.add_argument("session_id")

    p_command = sub.add_parser("command", help="queue a command for a session")
    p_command.add_argument("session_id")
    p_command.add_argument("verb")
    p_command.add_argument("--message", default=None, help="message for prompt/steer/follow_up/speak")
    p_command.add_argument("--request-id", default=None, help="optional dedupe key while command is queued")
    p_command.add_argument("--expires-in", type=float, default=None, help="seconds from now before command auto-expires")

    p_speak = sub.add_parser("speak", help="speak text on the device via TTS")
    p_speak.add_argument("text", nargs="+", help="words to speak")

    p_wait = sub.add_parser("wait-ping", help="block until the user pings")
    p_wait.add_argument("--timeout", type=float, default=600.0)

    p_clear = sub.add_parser("clear", help="return device to idle")

    p_snap = sub.add_parser("snapshot", help="set or clear ambient dashboard snapshot")
    p_snap.add_argument("--clear", action="store_true", help="remove the snapshot")
    p_snap.add_argument("--msg", default=None)
    p_snap.add_argument("--running", type=int, default=None)
    p_snap.add_argument("--waiting", type=int, default=None)
    p_snap.add_argument("--entries", action="append", default=None,
                        metavar="ENTRY", help="activity entry (newest first); repeat for each")
    p_snap.add_argument("--tokens-today", type=int, default=None,
                        dest="tokens_today")

    p_approve = sub.add_parser("approve", help="ask the user to approve a tool call")
    p_approve.add_argument("tool", help="tool name (e.g. Bash)")
    p_approve.add_argument("--hint", default="", help="context shown as body")
    p_approve.add_argument("--timeout", type=float, default=600.0)

    p_chirp = sub.add_parser("chirp", help="play a chirp on the device")
    p_chirp.add_argument("kind", nargs="?", default="good",
                         choices=["good", "bad"], help="good=ascending, bad=descending")

    p_bright = sub.add_parser("brightness", help="deprecated: brightness is local-only on device")
    p_bright.add_argument("pct", type=int, help="brightness percent (0-100)")

    p_mute = sub.add_parser("mute", help="deprecated: volume is local-only on device")
    p_mute.add_argument("state", nargs="?", default="on",
                        choices=["on", "off"], help="on=muted, off=unmuted")

    args = p.parse_args(argv)

    try:
        if args.cmd == "say":
            r = say(args.text, title=args.title, timeout=args.timeout)
            print(r if r is not None else "(timeout)")
            return 0
        if args.cmd == "ask":
            opts = args.option or ["yes", "no"]
            r = ask(args.title, body=args.body, options=opts, timeout=args.timeout)
            print(r if r is not None else "(timeout)")
            return 0
        if args.cmd == "pings":
            for p in recent_pings(n=args.n, strict=True):
                print(json.dumps(p))
            return 0
        if args.cmd == "status":
            print(json.dumps(status(n=args.n), indent=2))
            return 0
        if args.cmd == "overview":
            print(format_overview(status(n=args.n)))
            return 0
        if args.cmd == "healthcheck":
            out = healthcheck(
                max_oldest_prompt_s=args.max_oldest_prompt,
                max_oldest_command_s=args.max_oldest_command,
                max_stale_sessions=args.max_stale_sessions,
            )
            print(json.dumps(out, indent=2))
            return 0 if out.get("ok") else 1
        if args.cmd == "sessions":
            print(json.dumps(list_sessions(), indent=2))
            return 0
        if args.cmd == "session-stats":
            print(json.dumps(session_stats(), indent=2))
            return 0
        if args.cmd == "prompts":
            print(json.dumps(list_session_prompts(
                session_id=args.session_id,
                status=args.status,
                limit=args.limit,
            ), indent=2))
            return 0
        if args.cmd == "commands":
            print(json.dumps(list_commands(
                session_id=args.session_id,
                status=args.status,
                after_seq=args.after_seq,
                limit=args.limit,
            ), indent=2))
            return 0
        if args.cmd == "cancel-prompts":
            if args.dry_run:
                print(f"would cancel {count_pending_prompts(session_id=args.session_id)} prompt(s)")
            else:
                cancelled = cancel_pending_prompts(session_id=args.session_id)
                print(f"cancelled {cancelled} prompt(s)")
            return 0
        if args.cmd == "cancel-command":
            print(json.dumps(cancel_command(args.command_id, reason=args.reason), indent=2))
            return 0
        if args.cmd == "cancel-commands":
            if args.dry_run:
                print(f"would cancel {count_queued_commands(session_id=args.session_id)} command(s)")
            else:
                cancelled = cancel_queued_commands(session_id=args.session_id, reason=args.reason)
                print(f"cancelled {cancelled} command(s)")
            return 0
        if args.cmd == "cleanup-session":
            if args.dry_run:
                print(json.dumps({
                    "would_cancel_prompts": count_pending_prompts(session_id=args.session_id),
                    "would_cancel_commands": count_queued_commands(session_id=args.session_id),
                }, indent=2))
            else:
                print(json.dumps(cleanup_session(session_id=args.session_id, reason=args.reason), indent=2))
            return 0
        if args.cmd == "activate-session":
            print(json.dumps(activate_session(args.session_id), indent=2))
            return 0
        if args.cmd == "command":
            cmd_args = {"message": args.message} if args.message is not None else {}
            print(json.dumps(send_command(
                args.session_id,
                args.verb,
                cmd_args,
                request_id=args.request_id,
                expires_in=args.expires_in,
            ), indent=2))
            return 0
        if args.cmd == "wait-ping":
            r = wait_for_ping(timeout=args.timeout)
            print(json.dumps(r) if r else "(timeout)")
            return 0
        if args.cmd == "clear":
            clear()
            print("cleared")
            return 0
        if args.cmd == "snapshot":
            if args.clear:
                clear_snapshot()
                print("snapshot cleared")
            else:
                snap = snapshot(
                    running=args.running,
                    waiting=args.waiting,
                    msg=args.msg,
                    entries=args.entries,
                    tokens_today=args.tokens_today,
                )
                print(json.dumps(snap, indent=2))
            return 0
        if args.cmd == "approve":
            r = approve(args.tool, hint=args.hint, timeout=args.timeout)
            print(r if r is not None else "(timeout)")
            return 0
        if args.cmd == "speak":
            r = speak(" ".join(args.text))
            print(json.dumps(r))
            return 0
        if args.cmd == "chirp":
            r = chirp(args.kind)
            print(json.dumps(r))
            return 0
        if args.cmd == "brightness":
            r = set_brightness(args.pct)
            print(json.dumps(r))
            return 0
        if args.cmd == "mute":
            r = set_mute(args.state == "on")
            print(json.dumps(r))
            return 0
    except urllib.error.HTTPError as e:
        detail = str(e)
        try:
            payload = json.loads(e.read().decode("utf-8"))
            detail = payload.get("error") or detail
        except Exception:
            pass
        print(f"oi: server returned HTTP {e.code}: {detail}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, json.JSONDecodeError) as e:
        print(f"oi: cannot reach oi server at {SERVER_URL}: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
