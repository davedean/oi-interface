# AGENTS.md — oi-dashboard

## Project conventions

- Keep the dashboard lightweight: `aiohttp` backend + static HTML (`static/index.html`).

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
