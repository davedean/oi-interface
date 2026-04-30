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

## TODO (setup details to confirm)

- TODO: Document the canonical local setup for the `pi` command used by the default backend.
- TODO: Document where backend credentials are expected to be stored on developer machines.