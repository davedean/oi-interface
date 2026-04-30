# oi-cli

`oi-cli` is the command-line client for `oi-gateway`.
It calls the gateway HTTP API to list devices, check status, and send device commands.

## Quick run (no install)

```bash
cd src/oi-cli
python3 -m oi_cli devices
python3 -m oi_cli status
python3 -m oi_cli show-status --device oi-sim --state thinking --label "Working"
python3 -m oi_cli mute --device oi-sim --minutes 15
python3 -m oi_cli route --device oi-sim --text "Hello from oi-cli"
python3 -m oi_cli audio-play --device oi-sim
```

## Install

```bash
cd src/oi-cli
python3 -m pip install -e .
oi --help
```

## Development

Requires Python 3.11+.

```bash
cd src/oi-cli
python3 -m pytest tests -q
```

## Notes

- Default API URL: `http://localhost:8788`
- Use `--human` for text output; JSON is default.
- Use `--debug` to print unexpected tracebacks while developing.
- `--api-url` works both before and after the subcommand.
