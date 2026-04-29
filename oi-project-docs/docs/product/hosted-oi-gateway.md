# Hosted Oi Gateway

## Product thesis

Hosted Oi Gateway is a channel bridge, not a hosted agent.

It lets users talk to their existing agent from native Oi devices and apps.

```text
Apple Watch / iPhone / AirPods / M5Stick
  → hosted oi-gateway
    → OpenClaw / Hermes / Kimi-style agent / generic webhook
```

## User pitch

Talk to my agent from my wrist or phone without setting up Telegram.

## OpenClaw setup story

```text
1. Buy Oi app.
2. Subscribe to hosted Oi Gateway.
3. Get Gateway URL + channel UUID/token.
4. Add Oi channel to OpenClaw config.
5. Pair iPhone/Watch app.
6. Done.
```

## What the hosted gateway does

```text
pair devices/apps
maintain user/channel identity
receive voice/text/device events
forward events to configured agent channel endpoint
receive agent responses
deliver push notifications
manage cached response metadata
optionally handle STT/TTS
expose webhook/WebSocket/channel APIs
store minimal logs
```

## What it should avoid at first

```text
hosting arbitrary agents
running user tools
holding broad OAuth tokens
owning personal memory
being the canonical task ledger
executing code
```

## Why this is valuable

Agent systems often use Telegram, Discord, Slack, or WhatsApp as UI because they are convenient.

Oi Gateway provides a purpose-built personal agent channel:

- Watch complication;
- native push notifications;
- private earbud playback;
- short response constraints;
- native confirmations;
- rich phone detail view;
- no public chat app in the middle.

## Pricing idea

```text
Free/self-host:
  oi-server
  M5 firmware
  local plugins

Paid app:
  one-time app purchase

Hosted gateway:
  subscription for relay/push/channel service

Pro:
  more devices, more channels, longer audio retention, premium routing

Team:
  organization controls, audit, SSO later
```

## Privacy posture

The hosted gateway should store the minimum.

Store:

```text
user id
channel id
device ids
delivery tokens
routing config
billing state
short-lived audio blobs
recent delivery state
```

Avoid long-term storage of:

```text
full transcripts
agent memory
tool outputs
private long-form responses
attachments
```

Retention should be explicit.

## Business summary

You are not selling an AI assistant.

You are selling agent reachability:

```text
your agent
from your wrist
in your ears
without a chat app
without exposing your home server
with native confirmations
```
