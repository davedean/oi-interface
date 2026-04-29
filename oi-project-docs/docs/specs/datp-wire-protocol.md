# DATP: Device Agent Transport Protocol

Version: 0.1

## Purpose

DATP is the low-level bidirectional protocol between an embodied device and the gateway.

It is transport-agnostic but initially optimized for WebSocket over TLS or trusted LAN WebSocket.

## Design goals

- simple enough for microcontrollers;
- streaming audio support;
- explicit command acks;
- reconnectable;
- versioned;
- safe state machine support;
- no agent-specific assumptions in firmware.

## Transport

Initial:

```text
WebSocket:
  ws://gateway.local:8787/datp
  wss://gateway.example.com/datp
```

Future:

- MQTT;
- BLE to phone relay;
- QUIC/WebTransport;
- serial for development;
- LoRa/low-bandwidth variants.

## Envelope

All non-binary messages are JSON.

```json
{
  "v": "datp",
  "type": "event|command|ack|state|hello|hello_ack|error",
  "id": "msg_...",
  "device_id": "stick-pocket",
  "ts": "2026-04-27T04:40:00.000Z",
  "payload": {}
}
```

**Note:** Binary audio chunks are sent as JSON with base64 for simplicity. Binary WebSocket frames with preceding JSON metadata are planned for a future optimization pass.

## Hello

Device to gateway:

```json
{
  "v": "datp",
  "type": "hello",
  "id": "msg_001",
  "device_id": "stick-pocket",
  "ts": "2026-04-27T04:40:00.000Z",
  "payload": {
    "device_type": "oi-stick",
    "protocol": "datp",
    "firmware": "agent-stick-fw/0.3.0",
    "capabilities": {
      "audio_in": true,
      "audio_out": true,
      "display": "oled_128x64",
      "buttons": ["main", "a", "b"]
    },
    "state": {
      "mode": "READY",
      "battery_percent": 71,
      "charging": false,
      "wifi_rssi": -67
    },
    "resume_token": null,
    "nonce": "abc123def456"
  }
}
```

Gateway response:

```json
{
  "v": "datp",
  "type": "hello_ack",
  "id": "msg_002",
  "device_id": "stick-pocket",
  "payload": {
    "session_id": "sess_abc",
    "server_time": "2026-04-27T04:40:01.000Z",
    "accepted_protocol": "datp",
    "send_capabilities": true,
    "server_id": "oi-home",
    "server_name": "Home Oi",
    "default_agent": {
      "name": "default",
      "model": "claude-sonnet-4-20250514"
    },
    "available_agents": [],
    "server_capabilities": {
      "voice": true,
      "vision": false
    },
    "policy": {
      "require_pin": false
    }
  }
}
```

## Events

Button long-hold:

```json
{
  "v": "datp",
  "type": "event",
  "id": "evt_100",
  "device_id": "stick-pocket",
  "payload": {
    "event": "button.long_hold_started",
    "button": "main"
  }
}
```

Recording ended:

```json
{
  "v": "datp",
  "type": "event",
  "id": "evt_101",
  "device_id": "stick-pocket",
  "payload": {
    "event": "audio.recording_finished",
    "stream_id": "rec_42",
    "duration_ms": 4310
  }
}
```

## Audio chunk

```json
{
  "v": "datp",
  "type": "audio_chunk",
  "id": "aud_018",
  "device_id": "stick-pocket",
  "payload": {
    "stream_id": "rec_42",
    "seq": 18,
    "format": "pcm16",
    "sample_rate": 16000,
    "channels": 1,
    "data_b64": "..."
  }
}
```

## State report

```json
{
  "v": "datp",
  "type": "state",
  "id": "state_001",
  "device_id": "stick-pocket",
  "payload": {
    "mode": "READY",
    "battery_percent": 71,
    "charging": false,
    "wifi_rssi": -67,
    "heap_free": 132120,
    "uptime_s": 9231,
    "audio_cache_used_bytes": 580222,
    "muted_until": null
  }
}
```

## Command

```json
{
  "v": "datp",
  "type": "command",
  "id": "cmd_500",
  "device_id": "stick-pocket",
  "payload": {
    "op": "display.show_status",
    "args": {
      "state": "thinking",
      "label": "Checking repo"
    }
  }
}
```

Ack:

```json
{
  "v": "datp",
  "type": "ack",
  "id": "ack_500",
  "device_id": "stick-pocket",
  "payload": {
    "command_id": "cmd_500",
    "ok": true
  }
}
```

## Required commands

### `display.show_status`

```json
{
  "state": "idle|listening|thinking|response_cached|playing|confirm|muted|offline|error",
  "label": "short text"
}
```

### `display.show_card`

```json
{
  "title": "string",
  "options": [
    {"id": "yes", "label": "Yes"},
    {"id": "no", "label": "No"}
  ]
}
```

### `audio.cache.put_begin`

```json
{
  "response_id": "resp_123",
  "format": "wav_pcm16",
  "sample_rate": 22050,
  "bytes": 123456,
  "label": "short title"
}
```

### `audio.cache.put_chunk`

```json
{
  "response_id": "resp_123",
  "seq": 1,
  "data_b64": "..."
}
```

### `audio.cache.put_end`

```json
{
  "response_id": "resp_123",
  "sha256": "optional-sha256-hash-or-null"
}
```

- `sha256`: Optional SHA-256 hash of the complete audio data for verification. May be `null` if not calculated or not required.

### `audio.play`

```json
{
  "response_id": "latest|resp_123"
}
```

### `audio.stop`

```json
{}
```

### `device.set_brightness`

```json
{
  "value": 0
}
```

### `device.mute_until`

```json
{
  "until": "2026-04-27T05:10:00Z"
}
```

## Error shape

```json
{
  "v": "datp",
  "type": "error",
  "id": "err_123",
  "device_id": "stick-pocket",
  "payload": {
    "code": "INVALID_TRANSITION",
    "message": "Cannot play while recording",
    "related_id": "cmd_500"
  }
}
```

## Security

DATP should support:

- paired device identity;
- session tokens;
- TLS where possible;
- command nonce/replay prevention;
- gateway-side revocation;
- firmware-enforced command allowlist.

## Protocol philosophy

DATP is not a chatbot protocol. It is a body protocol.
