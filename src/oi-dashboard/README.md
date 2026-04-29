# Oi Dashboard

Real-time web dashboard for oi-gateway monitoring.

## Features

- Connected devices with status indicators
- Device state display (mode, battery, RSSI)
- Recent transcripts and responses
- Audio cache state per device
- Real-time updates via Server-Sent Events (SSE)

## Installation

```bash
pip install -e .
```

## Usage

```bash
oi-dashboard --api-url http://localhost:8788 --host localhost --port 8789
```

Then open `http://localhost:8789` in your browser.

## Development

```bash
pip install -e ".[dev]"
pytest tests/
```
