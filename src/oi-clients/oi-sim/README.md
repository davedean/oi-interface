# oi-sim

Virtual DATP device simulator for local Oi development and testing.

## Purpose

`oi-sim` impersonates a physical device and talks to `oi-gateway` over WebSocket so you can test input/output flows without hardware.

## Usage (rough)

```bash
cd src/oi-clients/oi-sim
python -m pip install -e ".[dev]"
oi-sim --gateway ws://localhost:8787/datp --device-id oi-sim-repl-001
```

In the REPL, type `help` for available commands (`hold`, `release`, `text`, `tap`, `gateway`, etc).

For scripted usage from Python, create an `OiSim`, connect it, then call helpers such as
`send_text_prompt()`, `press_long_hold()`, `release()`, or `replay_fixture()` from
`src/sim/fixtures.py`.

Typical first-time local setup:
1. Start `oi-gateway` so DATP is listening on `ws://localhost:8787/datp`.
2. Install the simulator in editable mode with dev dependencies.
3. Launch `oi-sim` and use `text`, `hold`, `release`, or `events` to inspect the flow.

## Development (rough)

- Core code lives in `src/sim/`.
- REPL entrypoint is `src/sim/repl.py`.
- Keep simulator behavior aligned with gateway protocol/state expectations.
- When state-machine semantics change, update both `src/sim/state.py` and the focused
  simulator/state tests in `tests/test_sim_state_machine.py` and `tests/test_sim_unit.py`
  together.

## Testing (rough)

```bash
cd src/oi-clients/oi-sim
pytest
```

Minimal smoke test:
```bash
# terminal 1
cd src/oi-gateway
PYTHONPATH=src python -m gateway_app

# terminal 2
cd src/oi-clients/oi-sim
oi-sim --gateway ws://localhost:8787/datp --device-id oi-sim-smoke
```
Then run `text hello`, `hold`, `release`, `gateway ws://other-host:8787/datp`, and `events` in the REPL to verify the round-trip.
