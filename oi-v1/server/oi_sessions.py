from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse


DEFAULT_SESSION_STALE_S = int(os.environ.get("OI_SESSION_STALE_S", "900"))
DEFAULT_SESSION_RETENTION_S = int(os.environ.get("OI_SESSION_RETENTION_S", str(14 * 24 * 3600)))
DEFAULT_MAX_COMPLETED_PROMPTS = int(os.environ.get("OI_MAX_COMPLETED_PROMPTS", "500"))
DEFAULT_MAX_FINISHED_COMMANDS = int(os.environ.get("OI_MAX_FINISHED_COMMANDS", "500"))


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def query_params(path: str) -> dict:
    parsed = urlparse(path)
    return {k: v[-1] for k, v in parse_qs(parsed.query).items() if v}


def _parse_iso_or_none(value: str | None):
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class SessionRouter:
    """Small persisted session/prompt/command router for oi."""

    def __init__(
        self,
        state_dir: Path,
        session_stale_s: int = DEFAULT_SESSION_STALE_S,
        session_retention_s: int = DEFAULT_SESSION_RETENTION_S,
        max_completed_prompts: int = DEFAULT_MAX_COMPLETED_PROMPTS,
        max_finished_commands: int = DEFAULT_MAX_FINISHED_COMMANDS,
    ):
        self.path = state_dir / "router.json"
        self._lock = threading.RLock()
        self._session_stale_s = max(0, int(session_stale_s))
        self._session_retention_s = max(0, int(session_retention_s))
        self._max_completed_prompts = max(0, int(max_completed_prompts))
        self._max_finished_commands = max(0, int(max_finished_commands))

    def _default(self) -> dict:
        return {
            "active_session_id": None,
            "next_prompt_seq": 1,
            "next_command_seq": 1,
            "sessions": {},
            "prompts": [],
            "commands": [],
        }

    def _load(self) -> dict:
        if not self.path.exists():
            return self._default()
        try:
            data = json.loads(self.path.read_text())
        except Exception:
            return self._default()
        default = self._default()
        for key, value in default.items():
            data.setdefault(key, value)
        return data

    def _save(self, data: dict) -> None:
        self._compact_history(data)
        atomic_write_json(self.path, data)

    def _compact_history(self, data: dict) -> None:
        """Bound router.json growth by keeping pending + recent completed records."""
        pending_prompts = [p for p in data["prompts"] if p.get("status") == "pending"]
        done_prompts = [p for p in data["prompts"] if p.get("status") != "pending"]
        done_prompts = sorted(done_prompts, key=lambda p: int(p.get("seq") or 0), reverse=True)
        data["prompts"] = pending_prompts + done_prompts[: self._max_completed_prompts]

        queued_commands = [c for c in data["commands"] if c.get("status") == "queued"]
        done_commands = [c for c in data["commands"] if c.get("status") != "queued"]
        done_commands = sorted(done_commands, key=lambda c: int(c.get("seq") or 0), reverse=True)
        data["commands"] = queued_commands + done_commands[: self._max_finished_commands]

        self._prune_sessions(data)

    def _prune_sessions(self, data: dict) -> None:
        """Drop long-stale sessions with no pending prompts/queued commands."""
        if self._session_retention_s <= 0:
            return
        live_session_ids = set()
        for prompt in data["prompts"]:
            if prompt.get("status") == "pending":
                sid = prompt.get("session_id")
                if isinstance(sid, str):
                    live_session_ids.add(sid)
        for command in data["commands"]:
            if command.get("status") == "queued":
                sid = command.get("session_id")
                if isinstance(sid, str):
                    live_session_ids.add(sid)

        active = data.get("active_session_id")
        now = datetime.now(timezone.utc)
        to_delete = []
        for sid, session in data["sessions"].items():
            if sid == active or sid in live_session_ids:
                continue
            last_seen = _parse_iso_or_none(session.get("last_seen"))
            if last_seen is None:
                continue
            age_s = int((now - last_seen).total_seconds())
            if age_s >= self._session_retention_s:
                to_delete.append(sid)

        for sid in to_delete:
            data["sessions"].pop(sid, None)

        active = data.get("active_session_id")
        if active is not None and active not in data["sessions"]:
            sessions = sorted(data["sessions"].values(), key=lambda s: s.get("last_seen", ""), reverse=True)
            data["active_session_id"] = sessions[0].get("session_id") if sessions else None

    def _expire_pending(self, data: dict) -> bool:
        """Mark expired pending prompts/queued commands based on expires_at."""
        now = datetime.now(timezone.utc)
        changed = False
        for prompt in data["prompts"]:
            if prompt.get("status") != "pending":
                continue
            expires_at = _parse_iso_or_none(prompt.get("expires_at"))
            if expires_at is not None and expires_at <= now:
                prompt["status"] = "expired"
                prompt["expired_at"] = now_iso()
                changed = True
        for command in data["commands"]:
            if command.get("status") != "queued":
                continue
            expires_at = _parse_iso_or_none(command.get("expires_at"))
            if expires_at is not None and expires_at <= now:
                command["status"] = "expired"
                command["result"] = "expired"
                command["finished_at"] = now_iso()
                changed = True
        return changed

    def _load_with_expiry(self) -> dict:
        data = self._load()
        if self._expire_pending(data):
            self._save(data)
        return data

    def _session_age_and_stale(self, session: dict) -> tuple[int | None, bool]:
        last_seen = _parse_iso_or_none(session.get("last_seen"))
        if last_seen is None:
            return None, False
        age = int((datetime.now(timezone.utc) - last_seen).total_seconds())
        age = max(0, age)
        return age, age >= self._session_stale_s

    def _effective_status(self, session: dict, stale: bool) -> str:
        status = str(session.get("status") or "unknown")
        if stale and status != "offline":
            return "offline"
        return status

    def upsert_session(self, payload: dict) -> dict:
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id required")
        with self._lock:
            data = self._load_with_expiry()
            current = data["sessions"].get(session_id, {})
            session = {
                **current,
                "session_id": session_id,
                "name": payload.get("name") or current.get("name") or session_id[:8],
                "cwd": payload.get("cwd") or current.get("cwd"),
                "kind": payload.get("kind") or current.get("kind") or "pi",
                "status": payload.get("status") or current.get("status") or "idle",
                "summary": payload.get("summary") if "summary" in payload else current.get("summary"),
                "model": payload.get("model") if "model" in payload else current.get("model"),
                "last_seen": now_iso(),
            }
            data["sessions"][session_id] = session
            if data.get("active_session_id") is None:
                data["active_session_id"] = session_id
            self._save(data)
            return session

    def list_sessions(self) -> dict:
        with self._lock:
            data = self._load_with_expiry()
            pending_counts = {}
            for prompt in data["prompts"]:
                if prompt.get("status") == "pending":
                    sid = prompt.get("session_id")
                    pending_counts[sid] = pending_counts.get(sid, 0) + 1

            active = data.get("active_session_id")
            def _sort_key(session):
                sid = session.get("session_id")
                return (
                    1 if sid == active else 0,
                    pending_counts.get(sid, 0),
                    session.get("last_seen", ""),
                )

            sessions = []
            for session in sorted(data["sessions"].values(), key=_sort_key, reverse=True):
                sid = session.get("session_id")
                age_s, stale = self._session_age_and_stale(session)
                effective_status = self._effective_status(session, stale)
                sessions.append({
                    **session,
                    "status": effective_status,
                    "reported_status": session.get("status"),
                    "pending_count": pending_counts.get(sid, 0),
                    "last_seen_age_s": age_s,
                    "stale": stale,
                })
            return {"active_session_id": data.get("active_session_id"), "sessions": sessions}

    def summary(self) -> dict:
        """Compact session summary safe to embed in legacy /oi/state for firmware UI."""
        with self._lock:
            data = self._load_with_expiry()
            pending_counts = {}
            for prompt in data["prompts"]:
                if prompt.get("status") == "pending":
                    sid = prompt.get("session_id")
                    pending_counts[sid] = pending_counts.get(sid, 0) + 1
            active = data.get("active_session_id")
            def _summary_sort(session):
                sid = session.get("session_id")
                return (
                    1 if sid == active else 0,
                    pending_counts.get(sid, 0),
                    session.get("last_seen", ""),
                )

            sessions = []
            for session in sorted(data["sessions"].values(), key=_summary_sort, reverse=True):
                sid = session.get("session_id")
                age_s, stale = self._session_age_and_stale(session)
                effective_status = self._effective_status(session, stale)
                sessions.append({
                    "session_id": sid,
                    "name": session.get("name"),
                    "status": effective_status,
                    "reported_status": session.get("status"),
                    "summary": session.get("summary"),
                    "pending_count": pending_counts.get(sid, 0),
                    "last_seen_age_s": age_s,
                    "stale": stale,
                })
            return {"active_session_id": data.get("active_session_id"), "sessions": sessions}

    def stats(self) -> dict:
        with self._lock:
            data = self._load_with_expiry()
            prompt_counts = {}
            for prompt in data["prompts"]:
                key = str(prompt.get("status") or "unknown")
                prompt_counts[key] = prompt_counts.get(key, 0) + 1
            command_counts = {}
            for command in data["commands"]:
                key = str(command.get("status") or "unknown")
                command_counts[key] = command_counts.get(key, 0) + 1
            stale_sessions = 0
            for session in data["sessions"].values():
                _, stale = self._session_age_and_stale(session)
                if stale:
                    stale_sessions += 1

            now = datetime.now(timezone.utc)
            pending_prompt_ages = []
            for prompt in data["prompts"]:
                if prompt.get("status") != "pending":
                    continue
                created = _parse_iso_or_none(prompt.get("created_at"))
                if created is not None:
                    pending_prompt_ages.append(max(0, int((now - created).total_seconds())))
            queued_command_ages = []
            for command in data["commands"]:
                if command.get("status") != "queued":
                    continue
                created = _parse_iso_or_none(command.get("created_at"))
                if created is not None:
                    queued_command_ages.append(max(0, int((now - created).total_seconds())))

            return {
                "active_session_id": data.get("active_session_id"),
                "session_count": len(data["sessions"]),
                "stale_session_count": stale_sessions,
                "oldest_pending_prompt_age_s": max(pending_prompt_ages) if pending_prompt_ages else None,
                "oldest_queued_command_age_s": max(queued_command_ages) if queued_command_ages else None,
                "prompts": {
                    "total": len(data["prompts"]),
                    "by_status": prompt_counts,
                },
                "commands": {
                    "total": len(data["commands"]),
                    "by_status": command_counts,
                },
            }

    def set_active(self, session_id: str | None) -> dict | None:
        with self._lock:
            data = self._load_with_expiry()
            if session_id is not None and session_id not in data["sessions"]:
                raise ValueError("unknown session_id")
            data["active_session_id"] = session_id
            self._save(data)
            return data["sessions"].get(session_id) if session_id else None

    def active_session(self) -> dict | None:
        with self._lock:
            data = self._load_with_expiry()
            sid = data.get("active_session_id")
            return data["sessions"].get(sid) if sid else None

    def _validate_options(self, options: list) -> None:
        for i, opt in enumerate(options):
            if not isinstance(opt, dict):
                raise ValueError(f"options[{i}] must be an object")
            if set(opt) != {"label", "value"}:
                raise ValueError(f"options[{i}] must contain label and value")
            if not isinstance(opt["label"], str) or not isinstance(opt["value"], str):
                raise ValueError(f"options[{i}].label/value must be strings")

    def create_prompt(self, payload: dict) -> dict:
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id required")
        for key in ("tool_use_id", "kind", "title", "body", "expires_at"):
            if key in payload and payload[key] is not None and not isinstance(payload[key], str):
                raise ValueError(f"{key} must be a string or null")
        options = payload.get("options") or [{"label": "ok", "value": "ok"}]
        if not isinstance(options, list):
            raise ValueError("options must be a list")
        self._validate_options(options)
        with self._lock:
            data = self._load_with_expiry()
            tool_use_id = payload.get("tool_use_id")
            if tool_use_id:
                for prompt in data["prompts"]:
                    if (prompt.get("session_id") == session_id and prompt.get("tool_use_id") == tool_use_id
                            and prompt.get("status") == "pending"):
                        return prompt
            seq = data["next_prompt_seq"]
            data["next_prompt_seq"] = seq + 1
            prompt = {
                "prompt_id": f"p-{seq}",
                "seq": seq,
                "session_id": session_id,
                "tool_use_id": tool_use_id,
                "kind": payload.get("kind") or "question",
                "title": payload.get("title") or "oi",
                "body": payload.get("body") or "",
                "options": options,
                "status": "pending",
                "response": None,
                "created_at": now_iso(),
                "expires_at": payload.get("expires_at"),
            }
            data["prompts"].append(prompt)
            self._save(data)
            return prompt

    def list_prompts(self, session_id: str | None = None, status: str | None = None,
                     limit: int | None = None) -> list:
        with self._lock:
            prompts = self._load_with_expiry()["prompts"]
            if session_id:
                prompts = [p for p in prompts if p.get("session_id") == session_id]
            if status and status not in {"all", "any"}:
                prompts = [p for p in prompts if p.get("status") == status]
            if limit is not None and limit > 0:
                prompts = prompts[-limit:]
            return prompts

    def get_prompt(self, prompt_id: str) -> dict | None:
        with self._lock:
            for prompt in self._load_with_expiry()["prompts"]:
                if prompt.get("prompt_id") == prompt_id:
                    return prompt
            return None

    def answer_prompt(self, prompt_id: str, value: str) -> dict | None:
        with self._lock:
            data = self._load_with_expiry()
            for prompt in data["prompts"]:
                if prompt.get("prompt_id") == prompt_id:
                    if prompt.get("status") != "pending":
                        return prompt
                    prompt["status"] = "answered"
                    prompt["response"] = value
                    prompt["answered_at"] = now_iso()
                    self._save(data)
                    return prompt
            return None

    def cancel_prompt(self, prompt_id: str) -> dict | None:
        with self._lock:
            data = self._load_with_expiry()
            for prompt in data["prompts"]:
                if prompt.get("prompt_id") == prompt_id:
                    if prompt.get("status") != "pending":
                        return prompt
                    prompt["status"] = "cancelled"
                    prompt["cancelled_at"] = now_iso()
                    self._save(data)
                    return prompt
            return None

    def cancel_pending_prompts(self, session_id: str | None = None) -> int:
        with self._lock:
            data = self._load_with_expiry()
            cancelled = 0
            for prompt in data["prompts"]:
                if prompt.get("status") != "pending":
                    continue
                if session_id and prompt.get("session_id") != session_id:
                    continue
                prompt["status"] = "cancelled"
                prompt["cancelled_at"] = now_iso()
                cancelled += 1
            if cancelled:
                self._save(data)
            return cancelled

    def projected_prompt_state(self) -> dict | None:
        with self._lock:
            data = self._load_with_expiry()
            pending = [p for p in data["prompts"] if p.get("status") == "pending"]
            if not pending:
                return None
            active = data.get("active_session_id")
            chosen = None
            if active:
                chosen = next((p for p in pending if p.get("session_id") == active), None)
            chosen = chosen or pending[0]
            session = data["sessions"].get(chosen.get("session_id"), {})
            return {
                "id": chosen["prompt_id"],
                "prompt_id": chosen["prompt_id"],
                "session_id": chosen.get("session_id"),
                "session_name": session.get("name"),
                "kind": chosen.get("kind"),
                "title": chosen.get("title"),
                "body": chosen.get("body"),
                "options": chosen.get("options") or [],
                "ts": chosen.get("created_at"),
            }

    def create_command(self, payload: dict) -> dict:
        session_id = payload.get("session_id")
        verb = payload.get("verb")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id required")
        if verb not in {"status", "abort", "steer", "follow_up", "prompt", "speak"}:
            raise ValueError("unsupported command verb")
        if "expires_at" in payload and payload["expires_at"] is not None and not isinstance(payload["expires_at"], str):
            raise ValueError("expires_at must be a string or null")
        request_id = payload.get("request_id")
        if request_id is not None and not isinstance(request_id, str):
            raise ValueError("request_id must be a string or null")
        args = payload.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError("args must be an object")
        with self._lock:
            data = self._load_with_expiry()
            if request_id:
                for command in data["commands"]:
                    if (command.get("session_id") == session_id
                            and command.get("request_id") == request_id
                            and command.get("status") == "queued"):
                        return command
            seq = data["next_command_seq"]
            data["next_command_seq"] = seq + 1
            command = {
                "command_id": f"c-{seq}",
                "seq": seq,
                "session_id": session_id,
                "verb": verb,
                "args": args,
                "request_id": request_id,
                "status": "queued",
                "created_at": now_iso(),
                "expires_at": payload.get("expires_at"),
                "result": None,
            }
            data["commands"].append(command)
            self._save(data)
            return command

    def list_commands(self, session_id: str | None = None, after_seq: int = 0,
                      status: str = "queued", limit: int | None = None) -> list:
        with self._lock:
            commands = self._load_with_expiry()["commands"]
            out = []
            for command in commands:
                if session_id and command.get("session_id") != session_id:
                    continue
                if int(command.get("seq") or 0) <= after_seq:
                    continue
                if status and status not in {"all", "any"} and command.get("status") != status:
                    continue
                out.append(command)
            if limit is not None and limit > 0:
                out = out[-limit:]
            return out

    def finish_command(self, command_id: str, status: str, result=None) -> dict | None:
        with self._lock:
            data = self._load_with_expiry()
            for command in data["commands"]:
                if command.get("command_id") == command_id:
                    command["status"] = status
                    command["result"] = result
                    command["finished_at"] = now_iso()
                    self._save(data)
                    return command
            return None

    def cancel_command(self, command_id: str, reason: str | None = None) -> dict | None:
        with self._lock:
            data = self._load_with_expiry()
            for command in data["commands"]:
                if command.get("command_id") != command_id:
                    continue
                if command.get("status") != "queued":
                    return command
                command["status"] = "cancelled"
                command["result"] = reason or "operator cancel"
                command["finished_at"] = now_iso()
                self._save(data)
                return command
            return None

    def cancel_queued_commands(self, session_id: str | None = None, reason: str | None = None) -> int:
        with self._lock:
            data = self._load_with_expiry()
            cancelled = 0
            for command in data["commands"]:
                if command.get("status") != "queued":
                    continue
                if session_id and command.get("session_id") != session_id:
                    continue
                command["status"] = "cancelled"
                command["result"] = reason or "operator bulk cancel"
                command["finished_at"] = now_iso()
                cancelled += 1
            if cancelled:
                self._save(data)
            return cancelled

    def cleanup_session(self, session_id: str | None = None, reason: str | None = None) -> dict:
        """Cancel pending prompts and queued commands in one atomic update."""
        with self._lock:
            data = self._load_with_expiry()
            cancelled_prompts = 0
            for prompt in data["prompts"]:
                if prompt.get("status") != "pending":
                    continue
                if session_id and prompt.get("session_id") != session_id:
                    continue
                prompt["status"] = "cancelled"
                prompt["cancelled_at"] = now_iso()
                cancelled_prompts += 1

            cancelled_commands = 0
            for command in data["commands"]:
                if command.get("status") != "queued":
                    continue
                if session_id and command.get("session_id") != session_id:
                    continue
                command["status"] = "cancelled"
                command["result"] = reason or "operator cleanup"
                command["finished_at"] = now_iso()
                cancelled_commands += 1

            if cancelled_prompts or cancelled_commands:
                self._save(data)
            return {
                "cancelled_prompts": cancelled_prompts,
                "cancelled_commands": cancelled_commands,
            }
