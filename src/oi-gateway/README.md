# Oi Gateway

Python gateway service for Oi v2. It handles DATP device transport, registry/state, agent-channel routing, and gateway APIs.

## Quick start

```bash
cd src/oi-gateway
pip install -e ".[dev]"
PYTHONPATH=src python -m gateway_app
```

Default ports (from `gateway_app.py`):
- DATP: `8787` (`OI_GATEWAY_PORT`)
- HTTP API: `8788` (`OI_GATEWAY_API_PORT`)

Backend selection (from `src/channel/factory.py`):
- `OI_AGENT_BACKEND=pi` (default; expects `pi` command on PATH, or set `OI_PI_COMMAND`)
- `OI_AGENT_BACKEND=hermes` (requires `OI_HERMES_BASE_URL` + `OI_HERMES_API_KEY`)
- `OI_AGENT_BACKEND=openclaw` (requires `OI_OPENCLAW_TOKEN`; see `OPENCLAW.md`)
- `OI_AGENT_BACKEND=piclaw` (requires `OI_PICLAW_BASE_URL`; optional `OI_PICLAW_SESSION_COOKIE` and/or `OI_PICLAW_INTERNAL_SECRET`, uses `/agent/side-prompt/stream` SSE)
- `OI_AGENT_BACKEND=opencode` (uses `opencode run --format json ...`; optional `OI_OPENCODE_COMMAND`)
- `OI_AGENT_BACKEND=codex` (uses `codex exec --json ...`; optional `OI_CODEX_COMMAND`)

## Development

```bash
cd src/oi-gateway
pip install -e ".[dev]"
PYTHONPATH=src pytest
```

Useful docs/examples:
- `OPENCLAW.md`
- `config.toml.example`
- `secrets.toml.example`

## PiClaw backend notes

The `piclaw` backend talks to a running PiClaw web runtime over HTTP/SSE.

Minimal setup:

```bash
export OI_AGENT_BACKEND=piclaw
export OI_PICLAW_BASE_URL=http://127.0.0.1:8080
```

Optional auth/session env:

```bash
export OI_PICLAW_SESSION_COOKIE=<piclaw_session token or full cookie string>
export OI_PICLAW_INTERNAL_SECRET=<internal secret if enabled>
export OI_PICLAW_CHAT_JID_PREFIX=oi-device-
export OI_PICLAW_SYSTEM_PROMPT='Keep responses brief for wearable/private playback.'
```

Notes:
- v1 uses PiClaw's `POST /agent/side-prompt/stream` interface.
- This gives streaming replies without depending on the full browser timeline/SSE chat flow.
- `OI_PICLAW_INTERNAL_SECRET` is sent both as `Authorization: Bearer ...` and `x-piclaw-internal-secret` for compatibility with PiClaw's trusted internal-secret auth path.

## TODO (setup details to confirm)

- TODO: Document the canonical local setup for the `pi` command used by the default backend.
- TODO: Document where backend credentials are expected to be stored on developer machines.
