"""Backend selection/configuration helpers for oi-gateway."""
from __future__ import annotations

import os
import shlex
from .backend import AgentBackend
from .codex_backend import CodexBackend
from .hermes_backend import HermesBackend
from .openclaw_backend import OpenClawBackend
from .opencode_backend import OpenCodeBackend
from .pi_backend import SubprocessPiBackend
from .piclaw_backend import PiclawBackend


def create_backend_from_env() -> AgentBackend:
    """Create the configured agent backend from environment variables."""
    backend = os.getenv("OI_AGENT_BACKEND", "pi").strip().lower()

    if backend == "pi":
        command = os.getenv("OI_PI_COMMAND")
        pi_command = shlex.split(command) if command else None
        return SubprocessPiBackend(pi_command=pi_command)

    if backend == "hermes":
        base_url = os.getenv("OI_HERMES_BASE_URL")
        api_key = os.getenv("OI_HERMES_API_KEY")
        if not base_url:
            raise ValueError("OI_HERMES_BASE_URL is required when OI_AGENT_BACKEND=hermes")
        if not api_key:
            raise ValueError("OI_HERMES_API_KEY is required when OI_AGENT_BACKEND=hermes")
        model = os.getenv("OI_HERMES_MODEL", "hermes")
        return HermesBackend(base_url=base_url, api_key=api_key, model=model)

    if backend == "openclaw":
        url = os.getenv("OI_OPENCLAW_URL", "ws://127.0.0.1:18789")
        token = os.getenv("OI_OPENCLAW_TOKEN")
        if not token:
            raise ValueError("OI_OPENCLAW_TOKEN is required when OI_AGENT_BACKEND=openclaw")
        timeout_seconds = float(os.getenv("OI_OPENCLAW_TIMEOUT_SECONDS", "120"))
        return OpenClawBackend(url=url, token=token, timeout_seconds=timeout_seconds)

    if backend == "piclaw":
        base_url = os.getenv("OI_PICLAW_BASE_URL")
        if not base_url:
            raise ValueError("OI_PICLAW_BASE_URL is required when OI_AGENT_BACKEND=piclaw")
        timeout_seconds = float(os.getenv("OI_PICLAW_TIMEOUT_SECONDS", "120"))
        session_cookie = os.getenv("OI_PICLAW_SESSION_COOKIE")
        internal_secret = os.getenv("OI_PICLAW_INTERNAL_SECRET")
        chat_jid_prefix = os.getenv("OI_PICLAW_CHAT_JID_PREFIX", "oi-device-")
        system_prompt = os.getenv("OI_PICLAW_SYSTEM_PROMPT")
        return PiclawBackend(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            session_cookie=session_cookie,
            internal_secret=internal_secret,
            chat_jid_prefix=chat_jid_prefix,
            system_prompt=system_prompt,
        )

    if backend == "opencode":
        command = os.getenv("OI_OPENCODE_COMMAND")
        timeout_seconds = float(os.getenv("OI_OPENCODE_TIMEOUT_SECONDS", "120"))
        return OpenCodeBackend.from_command_text(command, timeout_seconds=timeout_seconds)

    if backend == "codex":
        command = os.getenv("OI_CODEX_COMMAND")
        timeout_seconds = float(os.getenv("OI_CODEX_TIMEOUT_SECONDS", "120"))
        return CodexBackend.from_command_text(command, timeout_seconds=timeout_seconds)

    raise ValueError(f"Unsupported OI_AGENT_BACKEND: {backend}")
