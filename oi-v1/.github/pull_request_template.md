# Pull Request

## Description

_Describe what this PR does and why._

## Checklist

- [ ] Tests pass locally (`python3 -m pytest -q && npm --prefix mock-device run test:mock-device`)
- [ ] Code is linted (if applicable)

## Pi RPC parity checklist

If your PR touches any of:
- `firmware/lib/pi_rpc_*.py`
- `mock-device/src/pi_rpc_*.ts`
- `docs/pi_rpc_protocol_inventory.json`
- `scripts/check_pi_rpc_drift.py`

…then please confirm:

- [ ] `npm run rpc-parity-check` is green locally.
- [ ] If a new command/event/UI method was added: inventory updated, fixture added under `tests/fixtures/pi-rpc-wire/`, set-coverage tests pass.
- [ ] If a destructive command is touched (`bash`/`compact`/`fork`/`clone`/`export_html`): manual checklist (`docs/PI_RPC_MANUAL_CHECKLIST.md`) signed off in `WORKLOG.md`.
