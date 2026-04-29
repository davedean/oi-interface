# Oi Vision Update

## Name

The project is now called **Oi**.

The name works because:

- "oi!" is a human attention call;
- "I/O" backwards makes it a tiny input/output surface;
- it is short enough for a device, app, daemon, protocol, and brand;
- it feels less like a generic AI assistant and more like a weird, useful companion interface.

## What changed

The original idea was an M5Stick device to manage a Pi-hosted agent.

It is becoming something broader:

> Oi is an embodied channel layer for personal agents.

The local M5Stick version is still important, but it is now one embodiment among several:

```text
M5Stick:
  tiny tactile voice terminal

Raspberry Pi screen:
  rich local display / dashboard / kiosk

iPhone + Apple Watch + AirPods:
  mainstream mobile/private audio embodiment

Hosted oi-gateway:
  relay/channel bridge for existing agent systems

OpenClaw / Hermes / Kimi-style agents:
  backend brains that Oi can talk to
```

## Core product shape

Oi should not require people to adopt a new agent brain.

Oi should let people reach their existing agent from better surfaces:

```text
Talk to my agent from my wrist or earbuds without setting up Telegram.
```

This is the commercial wedge.

## Local-first and hosted can coexist

Self-hosted Oi remains the soul of the project:

```text
device → oi-server → local chief agent/tools/memory
```

Hosted Oi Gateway is convenience infrastructure:

```text
watch/phone/device → hosted oi-gateway → user's existing agent channel
```

The hosted gateway is not necessarily the agent. It is the embodied channel bridge.

## Design phrase

One mind, many bodies, many possible brains.

The "mind" is the user-facing continuity layer.  
The "bodies" are devices and apps.  
The "brains" may be local Oi, OpenClaw, Hermes, Kimi-style agents, or something else.
