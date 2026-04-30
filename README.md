# Oi

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
context.md                   ← current repo context and validation notes
handover.md                  ← latest handoff summary
BIG_TIDY_UP_PLAN.md          ← broader cleanup plan
PI_GATEWAY_INTEGRATION_PLAN.md ← Pi gateway integration notes
src/                         ← v2 implementation
  oi-gateway/                ← Python gateway: DATP, registry, STT/TTS, resource tree API
  oi-sim/                    ← virtual DATP device for dev and CI
  oi-cli/                    ← CLI wrapper over the gateway API
  oi-dashboard/              ← monitoring and debug dashboard
  oi-clients/                ← device client implementations and planning
oi-project-docs/             ← public specs and architecture docs
```

## Documentation

| Document | Purpose |
|---|---|
| [`context.md`](context.md) | Current repo context, findings, and validation notes |
| [`handover.md`](handover.md) | Latest handoff summary |
| [`BIG_TIDY_UP_PLAN.md`](BIG_TIDY_UP_PLAN.md) | Broader cleanup and follow-up plan |
| [`PI_GATEWAY_INTEGRATION_PLAN.md`](PI_GATEWAY_INTEGRATION_PLAN.md) | Pi gateway integration notes |
| [`OI_GATEWAY_FIRST_PASS_REVIEW.md`](OI_GATEWAY_FIRST_PASS_REVIEW.md) | Gateway review notes |
| [`OI_SIM_FIRST_PASS_REVIEW.md`](OI_SIM_FIRST_PASS_REVIEW.md) | Simulator review notes |
| [`start-oi.sh`](start-oi.sh) | Launcher for the gateway plus dashboard (`pi`, `hermes`, and `openclaw` backends) |
| [`src/oi-gateway/OPENCLAW.md`](src/oi-gateway/OPENCLAW.md) | OpenClaw backend setup and local wiring |
| [`src/oi-gateway/hermes.env.example`](src/oi-gateway/hermes.env.example) | Hermes backend env template |
| [`src/oi-gateway/openclaw.env.example`](src/oi-gateway/openclaw.env.example) | OpenClaw env template |
| [`oi-project-docs/docs/specs/`](oi-project-docs/docs/specs/) | Public wire protocol specs |
| [`oi-project-docs/docs/architecture/`](oi-project-docs/docs/architecture/) | Public architecture docs |
| [`oi-project-docs/docs/integrations/`](oi-project-docs/docs/integrations/) | Public ecosystem integration docs |

## Quick start

```bash
# Start gateway + dashboard together
./start-oi.sh start pi
# dashboard URL: http://localhost:8789
# LAN URL: http://<this-machine-ip>:8789

# Virtual device
cd src/oi-sim
python3 -m oi_sim

# CLI
cd src/oi-cli
python3 -m oi_cli devices
python3 -m oi_cli route --device oi-sim --text "Hello from Oi"

# Dashboard-only (manual)
cd src/oi-dashboard
oi-dashboard --api-url http://localhost:8788 --host 0.0.0.0 --port 8789

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
./start-oi.sh status
./start-oi.sh logs
```
