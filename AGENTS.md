# AGENTS.md

Scope: entire repository.

## Purpose

Oi is a local-first I/O layer for personal agents. Keep changes aligned with device/gateway/CLI/dashboard integration goals.

## Working rules

- Keep changes small and focused.
- Prefer test-first changes when practical.
- Do not invent behavior not reflected in code/docs; mark unknowns as `TODO`.
- Update docs with code changes when behavior, commands, or layout changes.

## Repo map

- `src/oi-gateway/` — gateway runtime, DATP, registry, STT/TTS, routing
- `src/oi-sim/` — virtual device simulator
- `src/oi-cli/` — CLI surface over gateway APIs
- `src/oi-dashboard/` — monitoring/debug UI
- `src/oi-clients/` — device client implementations/planning

## Validation

- Run targeted tests in the package you changed first.
- Before finishing broader work, run: `python3 runtests.py` from repo root.

## Style

- Keep files and functions readable; avoid unnecessary complexity.
- Prefer explicit, deterministic behavior at protocol/state boundaries.
