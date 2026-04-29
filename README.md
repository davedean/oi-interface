# Oi

> One mind. Many bodies. Human in control.

Oi is a local-first I/O bus for personal agents — tiny voice terminals and every device you already own.

Devices — a voice puck on your desk, a watch on your wrist, a phone in your pocket — are embodiments: they provide input, show state, and play back responses. Your agent (pi, OpenClaw, or any channel-compatible backend) runs the intelligence, makes routing decisions, and uses Oi as its surface. You decide when it speaks.

## What it is

- **Not another voice assistant.** Oi is an embodied I/O surface **for your existing agent**, not a standalone chatbot.
- **Local-first.** Runs entirely on a Pi or home server. Cloud is additive, never required.
- **Device-context aware.** Every message to the agent includes what devices are present, what they can do, and which is foreground — so your agent can make smart routing decisions.
- **Multi-device.** One agent, many bodies. M5Stick on the desk, Apple Watch on the wrist, desktop dashboard on screen, all driven by the same agent intelligence.
- **Firmware-protected interaction.** Button grammar is hardcoded in firmware; no remote agent can rebind it. User control is guaranteed even if the model behaves unexpectedly.

## Status

**✅ Phase 1 Complete** and **substantial Phase 2+ work is already implemented**.

Current subproject verification via `python3 runtests.py`:
- `oi-gateway`: 563 passed, 71 skipped
- `oi-sim`: 74 passed
- `oi-cli`: 30 passed
- `oi-dashboard`: 23 passed

Implemented and verified in the tree:
- Full DATP implementation with hello handshake
- oi-sim virtual device (scriptable, hardware-independent)
- Device registry + SQLite persistence
- STT (Whisper) + TTS (Piper) audio pipeline
- Channel integration with pi agent backend
- OpenClaw backend support via `OI_AGENT_BACKEND=openclaw`
- oi-cli tool interface + HTTP API
- End-to-end test suite
- Dashboard, character-pack support, routing/attention/multi-device scaffolding, and integration adapters

See [`PLAN.md`](PLAN.md) for the detailed build plan and current implementation notes, and [`TECH_DEBT.md`](TECH_DEBT.md) for cleanup items.

## Architecture

Oi is an **I/O bus for personal agents**, not an agent runtime itself. It provides:

### **Surfaces**
- DATP protocol to embodied devices (M5Stick, phones, watches, screens)
- Device registry with capability tracking
- STT/TTS pipeline (Whisper/Piper)
- Resource tree API exposed via `oi-cli`

### **Context**
- Device presence + capability injection into every agent message
- Foreground detection (which device the user is interacting with)
- Semantic status rendering (character packs)

### **Your Agent Does the Rest**
- Task management, memory, wiki, tool decisions → your agent (pi/OpenClaw)
- Routing choices → informed by device context from Oi
- Tool execution → via `oi-cli` during agent loop (same as any CLI tool)

### **Key Protocol Boundaries**
1. **DATP** – Device ↔ Gateway (WebSocket, audio streaming, commands)
2. **Oi Channel** – Gateway ↔ Agent (JSONL RPC to pi, HTTP webhook to others)
3. **Resource Tree API** – Agent ↔ Gateway (via `oi-cli` tool calls)

## Repo layout

```
PLAN.md              ← authoritative v2 build plan (start here)
src/                 ← v2 implementation
  oi-gateway/        ← Python gateway: DATP, device registry, STT/TTS, resource tree API
  oi-sim/            ← virtual DATP device (scriptable, dev/CI)
  oi-cli/            ← CLI wrapper over the gateway API
  oi-dashboard/      ← monitoring/debug dashboard
  oi-firmware/       ← firmware planning/scaffolding for device targets
oi-project-docs/     ← primary specs and architecture docs
oi-v1/               ← v1 reference codebase (do not modify)
```

## Hardware

Primary device: [M5Stack StickS3](https://docs.m5stack.com/en/core/M5StickS3) (ESP32-S3, 135×240 display, 2 buttons, mic, speaker, Wi-Fi, battery).

## Docs

| Document | Purpose |
|---|---|
| [`PLAN.md`](PLAN.md) | Full v2 plan: architecture, protocols, components, roadmap |
| [`TECH_DEBT.md`](TECH_DEBT.md) | Technical debt tracking from Phase 1 |
| [`ARCH_REVIEW.md`](ARCH_REVIEW.md) | Architectural review findings |
| [`start-oi.sh`](start-oi.sh) | Launcher for `pi`, `hermes`, and `openclaw` gateway runs |
| [`src/oi-gateway/hermes.env.example`](src/oi-gateway/hermes.env.example) | Hermes backend env template |
| [`src/oi-gateway/OPENCLAW.md`](src/oi-gateway/OPENCLAW.md) | OpenClaw backend setup and local env wiring |
| [`src/oi-gateway/openclaw.env.example`](src/oi-gateway/openclaw.env.example) | Example env file for the OpenClaw backend |
| [`oi-project-docs/docs/specs/`](oi-project-docs/docs/specs/) | Wire protocol specs (DATP, Oi Channel, etc.) |
| [`oi-project-docs/docs/plans/half-day-mvp.md`](oi-project-docs/docs/plans/half-day-mvp.md) | First demo target |
| [`oi-v1/README.md`](oi-v1/README.md) | v1 codebase overview |

## Getting Started

The core input+output loop is working end-to-end:

```bash
# Start oi-gateway (DATP + STT/TTS + API)
cd src/oi-gateway
python3 -m oi_gateway

# In another terminal, connect oi-sim (virtual device)
cd src/oi-sim
python3 -m oi_sim

# In another terminal, use oi-cli to drive devices
cd src/oi-cli
python3 -m oi_cli devices
python3 -m oi_cli route --device oi-sim --text "Hello from Oi"

# Dashboard (optional)
cd src/oi-dashboard
oi-dashboard --api-url http://localhost:8788 --host localhost --port 8789

# Or run the full test suite
cd src/oi-gateway && python3 -m pytest tests/ -q
cd src/oi-sim && python3 -m pytest tests/ -q

# From repo root, run all v2 subproject suites in isolation
python3 runtests.py
```

See [`PLAN.md`](PLAN.md) for the full 11-phase roadmap and [`TECH_DEBT.md`](TECH_DEBT.md) for current technical debt.

## OpenClaw

Oi can route agent traffic to a running OpenClaw Gateway over WebSocket RPC.
The wiring is documented in [`src/oi-gateway/OPENCLAW.md`](src/oi-gateway/OPENCLAW.md).

Use the launcher for backend selection:

```bash
./start-oi.sh start pi
./start-oi.sh start hermes
./start-oi.sh start openclaw
```
