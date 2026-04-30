from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SURPRISE_LABEL = "Surprise me ✨"
SURPRISE_PROMPTS = [
    "Tell me one oddly charming fact about today.",
    "Give me a tiny quest for the next 10 minutes.",
    "Invent a cheerful status update for this handheld.",
    "What is the most encouraging way to describe the weather today?",
    "Offer a one-line pep talk like a pocket wizard.",
]

CONNECTING_QUIPS = [
    "Wiggling antennae...",
    "Asking the gateway politely...",
    "Charging up pocket optimism...",
]

WAITING_QUIPS = [
    "Thinking delicious thoughts...",
    "Consulting the tiny council...",
    "Brewing an answer...",
    "Polishing electrons...",
]

CELEBRATION_NOTES = [
    "✨ Fresh from the gateway",
    "🌟 Pocket wisdom acquired",
    "🎉 Response cache warmed",
    "🪄 Tiny triumph unlocked",
]

SECRET_SEQUENCE = ["up", "up", "down", "down", "left", "right", "left", "right", "b", "a"]


@dataclass
class SecretTracker:
    progress: int = 0

    def push(self, button: str) -> bool:
        expected = SECRET_SEQUENCE[self.progress]
        if button == expected:
            self.progress += 1
            if self.progress == len(SECRET_SEQUENCE):
                self.progress = 0
                return True
            return False
        self.progress = 1 if button == SECRET_SEQUENCE[0] else 0
        return False


def cycle_pick(options: list[str], seed: int) -> str:
    if not options:
        return ""
    return options[seed % len(options)]


def pick_surprise_prompt(seed: int) -> str:
    return cycle_pick(SURPRISE_PROMPTS, seed)


def pick_connecting_quip(seed: int) -> str:
    return cycle_pick(CONNECTING_QUIPS, seed)


def pick_waiting_quip(seed: int) -> str:
    return cycle_pick(WAITING_QUIPS, seed)


def pick_celebration(seed: int) -> str:
    return cycle_pick(CELEBRATION_NOTES, seed)


def format_gateway_about(server_info: dict[str, Any] | None) -> list[str]:
    if not server_info:
        return ["No gateway metadata yet."]

    payload = server_info.get("payload", {}) if isinstance(server_info, dict) else {}
    lines = [
        f"Name: {payload.get('server_name') or payload.get('server_id') or 'Unknown gateway'}",
        f"Session: {payload.get('session_id') or 'n/a'}",
        f"Protocol: {payload.get('accepted_protocol') or 'datp'}",
    ]
    selected_backend = payload.get("selected_backend")
    if selected_backend:
        lines.append(f"Backend: {selected_backend}")
    selected_agent = payload.get("selected_agent") or payload.get("default_agent") or {}
    if isinstance(selected_agent, dict) and (selected_agent.get("name") or selected_agent.get("id")):
        lines.append(f"Agent: {selected_agent.get('name') or selected_agent.get('id')}")
    selected_session_key = payload.get("selected_session_key")
    if selected_session_key:
        lines.append(f"Chat: {selected_session_key}")
    available_backends = payload.get("available_backends") or []
    if isinstance(available_backends, list) and available_backends:
        names = []
        for backend in available_backends[:4]:
            if isinstance(backend, dict):
                names.append(backend.get("name") or backend.get("id") or "backend")
            else:
                names.append(str(backend))
        lines.append("Backends: " + ", ".join(names))
    available_agents = payload.get("available_agents") or []
    if isinstance(available_agents, list) and available_agents:
        names = []
        for agent in available_agents[:4]:
            if isinstance(agent, dict):
                names.append(agent.get("name") or agent.get("id") or "agent")
            else:
                names.append(str(agent))
        lines.append("Agents: " + ", ".join(names))
    return lines
