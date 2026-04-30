# AGENTS.md — oi-dashboard

## Scope

Applies to everything under:
- `src/oi-dashboard/`

## Project conventions

- Use project names exactly: `oi-dashboard`, `oi-gateway`.
- Keep the dashboard lightweight: `aiohttp` backend + static HTML (`static/index.html`).
- Prefer small, targeted changes over UI/framework rewrites.

## Runtime defaults

Defined in `src/oi_dashboard/dashboard.py`:
- host: `localhost`
- `oi-gateway` API port: `8788`
- `oi-dashboard` port: `8789`

Keep docs and CLI help aligned with these defaults unless intentionally changed.

## API/SSE surface

Current routes:
- `/`
- `/events` (SSE)
- `/api/devices`
- `/api/devices/{device_id}`
- `/api/transcripts`
- `/api/health`

When changing events or payloads, update tests and `README.md` in the same change.

## Dev/test

```bash
cd src/oi-dashboard
pip install -e ".[dev]"
pytest tests/
```
