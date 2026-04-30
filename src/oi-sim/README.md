# oi-sim

Virtual DATP device simulator for local Oi development and testing.

## Purpose

`oi-sim` impersonates a physical device and talks to `oi-gateway` over WebSocket so you can test input/output flows without hardware.

## Usage (rough)

```bash
cd src/oi-sim
python -m pip install -e ".[dev]"
oi-sim --gateway ws://localhost:8787/datp --device-id oi-sim-repl-001
```

In the REPL, type `help` for available commands (`hold`, `release`, `text`, `tap`, etc).

- TODO: add a scripted/non-interactive usage example.
- TODO: document expected gateway startup sequence for first-time setup.

## Development (rough)

- Core code lives in `src/sim/`.
- REPL entrypoint is `src/sim/repl.py`.
- Keep simulator behavior aligned with gateway protocol/state expectations.

- TODO: add a short "change checklist" for state-machine edits.

## Testing (rough)

```bash
cd src/oi-sim
pytest
```

- TODO: add a minimal end-to-end smoke test recipe (gateway + sim).
