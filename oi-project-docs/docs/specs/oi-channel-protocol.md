# Oi Channel Protocol

Version: 0.1 draft

## Purpose

Oi Channel Protocol connects Oi devices/apps/gateway to an agent backend.

Backends may include:

- OpenClaw;
- Hermes Agent;
- Kimi-style agents;
- generic webhook agents;
- local custom agents.

## Concept

Oi Gateway receives embodied user input and forwards it as a channel message.

The backend returns a response with delivery constraints.

```text
device/app → oi-gateway → agent channel
agent channel → oi-gateway → device/app
```

## Message endpoint

```http
POST /message
```

Request:

```json
{
  "channel_id": "ch_abc123",
  "message_id": "msg_001",
  "user": {
    "id": "user_123"
  },
  "source_device": {
    "id": "watch-user",
    "type": "apple_watch",
    "audio_route": "airpods"
  },
  "interaction": {
    "mode": "push_to_talk",
    "expects": "short_private_audio",
    "response_delivery": "notify_then_play"
  },
  "input": {
    "type": "text",
    "text": "what are you doing?"
  },
  "reply_constraints": {
    "max_spoken_seconds": 12,
    "supports_buttons": true,
    "supports_long_form": false,
    "private_audio": true
  }
}
```

## Response endpoint

```http
POST /response
```

Response:

```json
{
  "message_id": "msg_001",
  "response_id": "resp_001",
  "text": "I’m checking the deploy and waiting on one test.",
  "spoken_text": "I’m checking the deploy and waiting on one test.",
  "status": {
    "state": "response_ready",
    "label": "Deploy check"
  },
  "delivery": {
    "notify": true,
    "play_on_tap": true
  },
  "actions": []
}
```

## Confirmation request

```json
{
  "type": "confirmation_request",
  "id": "confirm_001",
  "title": "Apply patch?",
  "summary": "Change retry worker backoff.",
  "risk": "medium",
  "actions": [
    {"id": "approve", "label": "Approve"},
    {"id": "deny", "label": "Deny"},
    {"id": "details", "label": "Details"}
  ]
}
```

## Channel context prompt

For backends that only accept plain messages, the plugin can inject context:

```text
[Oi channel context]
The user spoke this through a wrist/earbud interface.
Prefer a short response suitable for private audio.
If the answer is long, summarize and provide a link/card.
If action requires confirmation, return a confirmation request.
```

## Structured metadata

Prompt context is not enough.

Where possible, pass structured metadata:

```json
{
  "reply_constraints": {
    "max_spoken_seconds": 12,
    "supports_markdown": false,
    "supports_confirm_buttons": true,
    "private_audio": true
  }
}
```

## Adapter strategy

```text
OpenClaw:
  native channel/plugin

Hermes Agent:
  channel/message bridge or delegated task endpoint

Generic webhook:
  POST message, receive response

Other agents:
  adapt if they expose API/channel/webhook
```

## Minimal backend contract

An agent backend must support:

```text
message in
response out
correlation id
error response
```

Optional:

```text
confirmation request
streaming status
long-form artifact link
tool/action callbacks
```
