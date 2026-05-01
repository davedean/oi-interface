# Agent Stick

A local-first, device-agnostic personal agent runtime with tiny embodied terminals.

The first terminal is an M5Stack StickS3-style voice puck: long-hold to record, double-tap to play the cached response, tiny screen for status, and a local server that runs STT, TTS, tools, memory, and agents.

The larger idea is more ambitious:

> One persistent personal agent session, many device embodiments, a safe capability surface, and a human-readable state model.

The device is not the assistant.  
The assistant is not the device.  
The device is one body the assistant can inhabit.

## Current interaction model

The project starts from a working prototype:

- The device records input when the human long-holds a button.
- The server runs speech-to-text.
- The agent produces a response.
- Text-to-speech audio is cached on the device.
- The human double-taps when they want to hear the response.
- The tiny screen shows status.
- The device can be muted, dimmed, and controlled through a device API.

This is intentionally not an always-listening speaker. Attention is explicit.

## Repository map

```text
docs/
  00-vision.md
  01-design-principles.md
  02-glossary.md
  architecture/
    system-overview.md
    agent-runtime.md
    device-runtime.md
    device-registry.md
    local-first-and-remote.md
    memory-and-wiki.md
  specs/
    device-capability-model.md
    datp-wire-protocol.md
    application-protocol.md
    human-interaction-spec.md
    character-status-spec.md
    tool-broker-and-permissions.md
    task-ledger.md
    security-model.md
  integrations/
    openclaw.md
    hermes-agent.md
    hermes-mqtt-rhasspy.md
    mcp.md
    home-assistant.md
  product/
    positioning.md
    user-stories.md
    design-language.md
  adr/
    0001-one-mind-many-bodies.md
    0002-device-owns-embodiment.md
  internal/        ← planning, ops, and reference notes
examples/
  datp-session.jsonl
  device-registry.json
schemas/
  device.schema.json
  command.schema.json
  event.schema.json
```

## Core claim

The valuable abstraction is not a custom voice assistant.

It is a **personal interaction fabric**:

- devices expose capabilities;
- the agent reasons about those capabilities;
- all risky action goes through a tool broker;
- devices remain deterministic and safe;
- the agent session persists across devices;
- human attention is treated as scarce;
- local-first is the default, remote is an explicit deployment mode.

## Non-goals for early versions

- Do not build a general phone replacement.
- Do not make the device run the agent.
- Do not give the agent arbitrary shell access from the start.
- Do not require wake-word capture.
- Do not require cloud services.
- Do not treat generated “memory” as truth without review.
- Do not integrate arbitrary third-party skills without sandboxing.

## Start here

Read:

1. `docs/00-vision.md`
2. `docs/architecture/system-overview.md`
3. `docs/specs/human-interaction-spec.md`
4. `docs/specs/datp-wire-protocol.md`

## Documentation index

### Foundations

- `docs/00-vision.md`
- `docs/01-design-principles.md`
- `docs/02-glossary.md`

### Architecture

- `docs/architecture/system-overview.md`
- `docs/architecture/agent-runtime.md`
- `docs/architecture/capability-aggregation.md`
- `docs/architecture/device-registry.md`
- `docs/architecture/device-runtime.md`
- `docs/architecture/local-first-and-remote.md`
- `docs/architecture/memory-and-wiki.md`
- `docs/architecture/server-device-agent-topology.md`

### Specs

- `docs/specs/application-protocol.md`
- `docs/specs/character-status-spec.md`
- `docs/specs/datp-wire-protocol.md`
- `docs/specs/device-capability-model.md`
- `docs/specs/human-interaction-spec.md`
- `docs/specs/oi-channel-protocol.md`
- `docs/specs/oi-device-handshake.md`
- `docs/specs/oi-resource-tree.md`
- `docs/specs/security-model.md`
- `docs/specs/task-ledger.md`
- `docs/specs/tool-broker-and-permissions.md`

### Integrations

- `docs/integrations/hermes-agent.md`
- `docs/integrations/hermes-mqtt-rhasspy.md`
- `docs/integrations/home-assistant.md`
- `docs/integrations/mcp.md`
- `docs/integrations/openclaw.md`

### Product

- `docs/product/apple-ecosystem.md`
- `docs/product/design-language.md`
- `docs/product/hosted-oi-gateway.md`
- `docs/product/positioning.md`
- `docs/product/user-stories.md`

### ADRs

- `docs/adr/0001-one-mind-many-bodies.md`
- `docs/adr/0002-device-owns-embodiment.md`
- `docs/adr/0003-api-source-proc-projection.md`
- `docs/adr/0004-hosted-gateway-not-hosted-agent.md`
- `docs/adr/0005-capabilities-aggregate-at-server.md`

### Examples and schemas

- `examples/datp-session.jsonl`
- `examples/device-registry.json`
- `examples/oi-handshake.json`
- `schemas/command.schema.json`
- `schemas/device.schema.json`
- `schemas/event.schema.json`
- `schemas/oi-channel-message.schema.json`

# Oi rename and strategic update

Working public name: **Oi**.

Interpretations:

- "oi!" as a tiny device/app that can get your attention;
- "I/O" backwards, because Oi is an input/output surface for an agent;
- short, speakable, slightly cheeky.

Suggested component names:

```text
oi           user-facing system / device family
oi-server    local gateway/runtime
oi-gateway   hosted relay/channel bridge
oi-fw        microcontroller firmware
oi-app       iOS/watchOS app
oi-claw      OpenClaw channel/plugin
oid          optional daemon binary name
```

Updated strategic split:

```text
oi-server:
  local runtime and device gateway

oi-app:
  iPhone / Apple Watch / AirPods client

oi-gateway:
  hosted relay and channel bridge

oi-channels:
  OpenClaw, Hermes, generic webhook, and future adapters
```

The first technical target remains:

```text
N devices → 1 oi-server → 1 chief agent
```

The commercial route can later be:

```text
Apple Watch / iPhone / AirPods
  → hosted oi-gateway
    → OpenClaw/Hermes/other agent as a channel
```
