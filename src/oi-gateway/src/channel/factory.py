"""Backend selection/configuration helpers for oi-gateway."""
from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass

from .backend import AgentBackend
from .codex_backend import CodexBackend
from .hermes_backend import HermesBackend
from .openclaw_backend import OpenClawBackend
from .opencode_backend import OpenCodeBackend
from .pi_backend import SubprocessPiBackend
from .piclaw_backend import PiclawBackend


@dataclass(frozen=True)
class BackendProfile:
    id: str
    label: str
    backend: AgentBackend


class BackendCatalog:
    def __init__(self, profiles: list[BackendProfile], default_backend_id: str) -> None:
        if not profiles:
            raise ValueError("at least one backend profile is required")
        self._profiles = {profile.id: profile for profile in profiles}
        if default_backend_id not in self._profiles:
            raise ValueError(f"unknown default backend id: {default_backend_id}")
        self.default_backend_id = default_backend_id

    def get(self, backend_id: str | None) -> AgentBackend:
        selected = backend_id or self.default_backend_id
        profile = self._profiles.get(selected)
        if profile is None:
            return self._profiles[self.default_backend_id].backend
        return profile.backend

    def available_backends(self) -> list[dict[str, str]]:
        return [
            {
                "id": profile.id,
                "name": profile.label,
                "backend": getattr(profile.backend, "name", profile.id),
            }
            for profile in self._profiles.values()
        ]


def _backend_name_from_env() -> str:
    return os.getenv("OI_AGENT_BACKEND", "pi").strip().lower()


def _backend_from_type(backend_type: str, config: dict[str, object] | None = None) -> AgentBackend:
    config = config or {}

    if backend_type == "pi":
        command = config.get("command") or os.getenv("OI_PI_COMMAND")
        timeout_seconds = float(config.get("timeout_seconds") or 60.0)
        pi_command = shlex.split(command) if isinstance(command, str) and command else None
        return SubprocessPiBackend(pi_command=pi_command, timeout_seconds=timeout_seconds)

    if backend_type == "hermes":
        base_url = str(config.get("base_url") or os.getenv("OI_HERMES_BASE_URL") or "")
        api_key = str(config.get("api_key") or os.getenv("OI_HERMES_API_KEY") or "")
        if not base_url:
            raise ValueError("OI_HERMES_BASE_URL is required when OI_AGENT_BACKEND=hermes")
        if not api_key:
            raise ValueError("OI_HERMES_API_KEY is required when OI_AGENT_BACKEND=hermes")
        model = str(config.get("model") or os.getenv("OI_HERMES_MODEL", "hermes"))
        return HermesBackend(base_url=base_url, api_key=api_key, model=model)

    if backend_type == "openclaw":
        url = str(config.get("url") or os.getenv("OI_OPENCLAW_URL", "ws://127.0.0.1:18789"))
        token = str(config.get("token") or os.getenv("OI_OPENCLAW_TOKEN") or "")
        if not token:
            raise ValueError("OI_OPENCLAW_TOKEN is required when OI_AGENT_BACKEND=openclaw")
        timeout_seconds = float(config.get("timeout_seconds") or os.getenv("OI_OPENCLAW_TIMEOUT_SECONDS", "120"))
        return OpenClawBackend(url=url, token=token, timeout_seconds=timeout_seconds)

    if backend_type == "piclaw":
        base_url = str(config.get("base_url") or os.getenv("OI_PICLAW_BASE_URL") or "")
        if not base_url:
            raise ValueError("OI_PICLAW_BASE_URL is required when OI_AGENT_BACKEND=piclaw")
        timeout_seconds = float(config.get("timeout_seconds") or os.getenv("OI_PICLAW_TIMEOUT_SECONDS", "120"))
        session_cookie = config.get("session_cookie") or os.getenv("OI_PICLAW_SESSION_COOKIE")
        internal_secret = config.get("internal_secret") or os.getenv("OI_PICLAW_INTERNAL_SECRET")
        chat_jid_prefix = str(config.get("chat_jid_prefix") or os.getenv("OI_PICLAW_CHAT_JID_PREFIX", "oi-device-"))
        system_prompt = config.get("system_prompt") or os.getenv("OI_PICLAW_SYSTEM_PROMPT")
        return PiclawBackend(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            session_cookie=str(session_cookie) if session_cookie else None,
            internal_secret=str(internal_secret) if internal_secret else None,
            chat_jid_prefix=chat_jid_prefix,
            system_prompt=str(system_prompt) if system_prompt else None,
        )

    if backend_type == "opencode":
        command = config.get("command") or os.getenv("OI_OPENCODE_COMMAND")
        timeout_seconds = float(config.get("timeout_seconds") or os.getenv("OI_OPENCODE_TIMEOUT_SECONDS", "120"))
        return OpenCodeBackend.from_command_text(str(command) if command else None, timeout_seconds=timeout_seconds)

    if backend_type == "codex":
        command = config.get("command") or os.getenv("OI_CODEX_COMMAND")
        timeout_seconds = float(config.get("timeout_seconds") or os.getenv("OI_CODEX_TIMEOUT_SECONDS", "120"))
        return CodexBackend.from_command_text(str(command) if command else None, timeout_seconds=timeout_seconds)

    raise ValueError(f"Unsupported OI_AGENT_BACKEND: {backend_type}")


def create_backend_from_env() -> AgentBackend:
    """Create the configured agent backend from environment variables."""
    return _backend_from_type(_backend_name_from_env())


def create_backend_catalog_from_env() -> BackendCatalog:
    raw = os.getenv("OI_AGENT_BACKENDS_JSON", "").strip()
    if not raw:
        backend = create_backend_from_env()
        backend_name = _backend_name_from_env()
        return BackendCatalog(
            [BackendProfile(id=backend_name, label=backend_name.title(), backend=backend)],
            default_backend_id=backend_name,
        )

    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise ValueError("OI_AGENT_BACKENDS_JSON must be a non-empty JSON array")

    profiles: list[BackendProfile] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError("each backend profile must be an object")
        backend_id = str(item.get("id") or "").strip()
        if not backend_id:
            raise ValueError(f"backend profile at index {index} is missing id")
        backend_type = str(item.get("backend") or backend_id).strip().lower()
        label = str(item.get("label") or backend_id)
        profiles.append(BackendProfile(id=backend_id, label=label, backend=_backend_from_type(backend_type, item)))

    default_backend_id = str(os.getenv("OI_DEFAULT_AGENT_BACKEND_ID") or profiles[0].id)
    return BackendCatalog(profiles, default_backend_id=default_backend_id)
