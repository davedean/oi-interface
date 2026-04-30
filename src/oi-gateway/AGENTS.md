# AGENTS.md — `src/oi-gateway`

## Scope

Instructions here apply to work in `src/oi-gateway/`.

## Start here

1. Read `pyproject.toml` for dependency/test settings.
2. Read `src/gateway_app.py` for runtime wiring and env defaults.
3. Read relevant tests in `tests/` before changing behavior.

## Working rules

- Keep edits narrow and consistent with existing module boundaries.
- Prefer test-first changes when practical.
- Do not edit `character_packs.db*` files unless the task explicitly requires data changes.
- If setup details are unclear, write `TODO` notes instead of guessing environment-specific behavior.

## Validation

Run targeted tests first, then broader tests if needed:

```bash
cd src/oi-gateway
PYTHONPATH=src pytest tests/test_gateway_app.py -q
PYTHONPATH=src pytest
```

## Known docs

- OpenClaw backend setup: `OPENCLAW.md`
- Env templates: `hermes.env.example`, `openclaw.env.example`

## TODO (repo-specific agent workflow)

- TODO: Confirm whether this subproject has required smoke tests beyond `pytest`.
- TODO: Confirm preferred local run command for manual gateway verification in this directory.