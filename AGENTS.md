# AGENTS.md

## Purpose

Oi is a local-first I/O layer for personal agents. Keep changes aligned with device/gateway/CLI/dashboard integration goals.

## Repo map

- `src/oi-gateway/` — gateway runtime, DATP, registry, STT/TTS, routing
- `src/oi-cli/` — CLI surface over gateway APIs
- `src/oi-dashboard/` — monitoring/debug UI
- `src/oi-clients/` — device client implementations/planning, including `oi-sim`

## Logs 

$ find ~/.oi/logs/
