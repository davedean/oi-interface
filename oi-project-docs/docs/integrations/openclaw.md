# Integration: OpenClaw

## Current understanding

OpenClaw is a personal AI assistant you run on your own devices. Its GitHub README describes a gateway/control-plane architecture, many messaging channels, voice support on macOS/iOS/Android, and a live Canvas. It positions the gateway as the control plane, while "the product is the assistant."

## How Agent Stick should relate to OpenClaw

Treat OpenClaw as an optional integration backend, not the root authority.

Recommended shape:

```text
Agent Stick chief agent
  → tool broker
    → OpenClaw adapter
      → OpenClaw gateway/channels/skills/canvas
```

Avoid:

```text
M5Stick → OpenClaw owns everything
```

## Possible uses

- send/receive messages through OpenClaw channels;
- use OpenClaw Canvas as a rich display surface;
- expose Agent Stick device status into OpenClaw;
- allow OpenClaw skills as brokered tools;
- use OpenClaw as hosted gateway for non-local channels.

## Adapter contract

```json
{
  "tool": "openclaw.send_message",
  "risk": "high",
  "args": {
    "channel": "telegram",
    "target": "user_or_chat",
    "message": "..."
  }
}
```

```json
{
  "tool": "openclaw.render_canvas",
  "risk": "low",
  "args": {
    "title": "Agent Stick task report",
    "markdown": "..."
  }
}
```

## Security notes

OpenClaw-like skill ecosystems are powerful because they can extend the assistant. They are risky because skills may combine instructions, executable code, local file access, credentials, and network access.

Agent Stick should:

- never install skills from the device alone;
- require review on a rich surface;
- sandbox OpenClaw skills;
- avoid sharing Agent Stick secrets with OpenClaw by default;
- use separate credentials where possible;
- log every OpenClaw tool call.

## Product posture

OpenClaw may be a great early bridge to existing chat channels. Agent Stick's differentiation is embodiment, device routing, local-first tiny terminals, and a stricter capability/permission model.

## Oi Gateway channel model

The preferred commercial integration is:

```text
Oi app/device
  → hosted oi-gateway
    → OpenClaw Oi Channel plugin
      → OpenClaw agent
```

OpenClaw does not need to know how to talk to M5Stick, Apple Watch, or AirPods.

It only needs a channel plugin that can receive Oi messages and return Oi responses.

Example OpenClaw config:

```yaml
plugins:
  oi:
    gateway_url: "https://gateway.example.com"
    channel_id: "ch_abc123"
    token: "${OI_CHANNEL_TOKEN}"
```

The plugin should inject Oi interaction context into messages and preserve structured metadata where possible.
