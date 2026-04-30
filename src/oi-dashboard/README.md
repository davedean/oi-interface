# oi-dashboard

Real-time monitoring dashboard for `oi-gateway`.

## What it shows

- Connected devices and online/offline status
- Device state (for example mode, battery, RSSI when available)
- Recent transcripts and agent responses
- Audio cache size by device
- Live updates via Server-Sent Events (SSE)

## Requirements

- Python 3.11+
- A running `oi-gateway` API (default expected at `http://localhost:8788`)

## Quick start

```bash
cd src/oi-dashboard
pip install -e .
oi-dashboard --api-url http://localhost:8788 --host localhost --port 8789
```

Open `http://localhost:8789`.

If your gateway runs elsewhere, change `--api-url`.

## Development

```bash
cd src/oi-dashboard
pip install -e ".[dev]"
pytest tests/
```

## Notes

- The dashboard is read-only and proxies selected gateway API endpoints.
- `/events` emits standard SSE `message` frames whose JSON body has the shape `{ "type": ..., "data": ... }`.
- `/api/transcripts` returns serialized transcript objects with `timestamp`, `device_id`, `transcript`, `response`, and `stream_id` fields.
- TODO: add a short local dev stack example that starts `oi-gateway` + `oi-dashboard` together.
