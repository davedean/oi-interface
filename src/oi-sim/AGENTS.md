# AGENTS.md — oi-sim

## Scope

Applies to everything under `src/oi-sim/`.

## Purpose

Keep `oi-sim` as a simple, reliable virtual DATP device for local development and CI.

## Usage (rough)

```bash
cd src/oi-sim
python -m pip install -e ".[dev]"
oi-sim --gateway ws://localhost:8787/datp --device-id oi-sim-repl-001
```

Use `help` in the REPL to inspect supported simulated events.

- TODO: add a documented scripted session/replay flow.

## Development (rough)

- If command semantics change, keep REPL help text and tests in sync.

- TODO: add protocol versioning notes if/when the simulator supports multiple profiles.

## Testing (rough)

```bash
cd src/oi-sim
pytest
```

- TODO: add a quick command for running only state-transition tests.
