# AGENTS.md (oi-cli)

Scope: this guidance applies to `src/oi-cli` only.

## Working rules

- Keep changes small and focused.
- Follow existing CLI patterns (`argparse`, JSON default output, optional `--human`).
- Avoid unrelated refactors unless explicitly requested.

## Testing

- Run package tests before handoff:

```bash
cd src/oi-cli
python3 -m pytest tests -q
```

- If CLI behavior changes, add or update targeted tests in `tests/test_cli.py`.

## Style

- Prefer clear command/help text and predictable exit codes.
- Keep API calls and output formatting simple and explicit.
