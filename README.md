# Oi

> One mind. Many bodies. Human in control.

Oi is a local-first input/output layer for personal agents. It connects embodied devices, a gateway, and a user-owned agent runtime so you can interact with the same assistant from a desk puck, phone, watch, dashboard, or terminal.

## What it does

- Captures explicit user input from devices, not always-on listening.
- Routes device context into agent requests so responses can fit the active surface.
- Keeps device behavior deterministic, with a fixed button grammar and safe state transitions.
- Supports local-first operation with optional hosted bridges and third-party agent backends.

## Current state

The core loop is implemented in-tree and verified across the main subprojects.

Included today:

- DATP device transport
- `oi-sim` virtual device
- device registry and state persistence
- STT and TTS pipeline
- `oi-cli` command surface
- dashboard and integration scaffolding
- OpenClaw backend support

## Architecture

Oi is an I/O bus for personal agents, not the agent runtime itself.

### Surfaces

- DATP protocol to embodied devices
- device registry with capability tracking
- STT/TTS pipeline
- resource tree API exposed via `oi-cli`

### Context

- device presence and capabilities
- foreground detection
- semantic status rendering

### Agent responsibilities

- task management
- memory and wiki decisions
- tool selection
- routing decisions informed by device context

### Protocol boundaries

1. `DATP` - device to gateway
2. `Oi Channel` - gateway to agent
3. `Resource Tree API` - agent to gateway

## Repository layout

```text
PLAN.md              ← project plan and implementation notes
src/                 ← v2 implementation
  oi-gateway/        ← Python gateway: DATP, registry, STT/TTS, resource tree API
  oi-sim/            ← virtual DATP device for dev and CI
  oi-cli/            ← CLI wrapper over the gateway API
  oi-dashboard/      ← monitoring and debug dashboard
  oi-firmware/       ← firmware planning and scaffolding
oi-project-docs/     ← public specs and architecture docs
```

## Documentation

| Document | Purpose |
|---|---|
| [`PLAN.md`](PLAN.md) | Project plan and implementation notes |
| [`TECH_DEBT.md`](TECH_DEBT.md) | Current cleanup and follow-up items |
| [`ARCH_REVIEW.md`](ARCH_REVIEW.md) | Architecture review notes |
| [`start-oi.sh`](start-oi.sh) | Launcher for `pi`, `hermes`, and `openclaw` gateway runs |
| [`src/oi-gateway/OPENCLAW.md`](src/oi-gateway/OPENCLAW.md) | OpenClaw backend setup and local wiring |
| [`src/oi-gateway/hermes.env.example`](src/oi-gateway/hermes.env.example) | Hermes backend env template |
| [`src/oi-gateway/openclaw.env.example`](src/oi-gateway/openclaw.env.example) | OpenClaw env template |
| [`oi-project-docs/docs/specs/`](oi-project-docs/docs/specs/) | Public wire protocol specs |
| [`oi-project-docs/docs/integrations/`](oi-project-docs/docs/integrations/) | Public ecosystem integration docs |

## Quick start

```bash
# Gateway
cd src/oi-gateway
python3 -m oi_gateway

# Virtual device
cd src/oi-sim
python3 -m oi_sim

# CLI
cd src/oi-cli
python3 -m oi_cli devices
python3 -m oi_cli route --device oi-sim --text "Hello from Oi"

# Dashboard
cd src/oi-dashboard
oi-dashboard --api-url http://localhost:8788 --host localhost --port 8789

# Full test run
python3 runtests.py
```

## OpenClaw

Oi can route agent traffic to a running OpenClaw gateway over WebSocket RPC.
The wiring is documented in [`src/oi-gateway/OPENCLAW.md`](src/oi-gateway/OPENCLAW.md).

```bash
./start-oi.sh start pi
./start-oi.sh start hermes
./start-oi.sh start openclaw
```
