# oi-cli

`oi-cli` is the command-line client for `oi-gateway`.
It calls the gateway HTTP API to list devices, check status, and send device commands.

## Quick run (no install)

```bash
cd src/oi-cli
python3 -m oi_cli devices
python3 -m oi_cli status
python3 -m oi_cli route --device oi-sim --text "Hello from oi-cli"
```

## Install

```bash
cd src/oi-cli
python3 -m pip install -e .
oi --help
```

> TODO: confirm whether editable install is the preferred workflow for all contributors.

## Development

```bash
cd src/oi-cli
# TODO: add/confirm any required local env setup steps beyond Python 3.11+
python3 -m pytest tests -q
```

## Test

```bash
cd src/oi-cli
python3 -m pytest tests -q
```

## Notes

- Default API URL: `http://localhost:8788`
- Use `--human` for text output; JSON is default.
