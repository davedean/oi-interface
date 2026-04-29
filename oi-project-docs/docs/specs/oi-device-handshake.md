# Oi Device Handshake

Version: 0.1

## Purpose

When a device joins an Oi server, both sides exchange enough information to establish identity, capabilities, policy, and future routing options.

The device does not need the whole system graph.  
The server does.

## Device hello

```json
{
  "v": "datp",
  "type": "hello",
  "id": "msg_hello_001",
  "device_id": "oi-stick-001",
  "ts": "2026-04-27T04:40:00.000Z",
  "payload": {
    "device_type": "oi-stick",
    "protocol": "datp",
    "firmware": "oi-stick-fw/0.1.0",
    "capabilities": {
      "input": ["hold_to_record", "double_tap", "button_confirm"],
      "output": ["tiny_screen", "cached_audio", "character"],
      "sensors": ["battery", "wifi_rssi"],
      "commands_supported": [
        "display.show_status",
        "display.show_card",
        "character.set_state",
        "audio.cache_put",
        "audio.play",
        "device.set_brightness",
        "device.mute_until"
      ]
    },
    "state": {
      "mode": "READY",
      "battery_percent": 81,
      "wifi_rssi": -62
    },
    "resume_token": null,
    "nonce": "abc123def456"
  }
}
```

## Server hello ack

```json
{
  "v": "datp",
  "type": "hello_ack",
  "id": "ack_hello_001",
  "device_id": "oi-stick-001",
  "ts": "2026-04-27T04:40:01.000Z",
  "payload": {
    "server_id": "oi-home",
    "server_name": "Home Oi",
    "protocol": "datp",
    "session_id": "sess_abc",
    "server_time": "2026-04-27T04:40:01.000Z",
    "accepted_protocol": "datp",
    "send_capabilities": true,
    "default_agent": {
      "id": "chief",
      "name": "Oi",
      "role": "primary"
    },
    "available_agents": [
      {
        "id": "chief",
        "name": "Oi",
        "role": "primary",
        "accepts_direct_input": true
      },
      {
        "id": "coding",
        "name": "Coding",
        "role": "worker",
        "accepts_direct_input": false
      }
    ],
    "server_capabilities": {
      "stt": ["whisper_local"],
      "tts": ["piper_local"],
      "routing": true,
      "task_ledger": true,
      "rich_display_available": true,
      "confirmations": true
    },
    "policy": {
      "default_target_agent": "chief",
      "device_may_select_agent": false,
      "max_recording_seconds": 60,
      "auto_speak_allowed": false
    }
  }
}
```

## MVP behaviour

For MVP, a device may ignore most server details and simply display:

```text
Home Oi
Ready
```

But the handshake should include future fields so the protocol does not need to be redesigned later.

## Periodic refresh

Capabilities are not static.

Examples:

- Pi screen joins or leaves;
- phone switches audio route to AirPods;
- Apple Watch enters low-power mode;
- Home Assistant integration goes down;
- server gains OpenClaw channel;
- TTS provider changes.

Required update messages:

```text
capabilities_update
state_update
policy_update
heartbeat
```

## Device capabilities update

```json
{
  "type": "capabilities_update",
  "device_id": "pi-kiosk-desk",
  "capabilities": {
    "output": ["large_screen", "touch_confirmation", "markdown"],
    "input": ["touch", "keyboard"],
    "state": {
      "display_on": true,
      "locked": false
    }
  }
}
```

## Server policy update

```json
{
  "type": "policy_update",
  "server_id": "oi-home",
  "policy": {
    "max_recording_seconds": 90,
    "device_may_select_agent": true,
    "available_agent_menu": ["chief", "coding"]
  }
}
```

## Device knowledge boundary

Devices should not need to know the full system graph.

The Stick does not need to know the Pi screen exists.

The server/agent can route:

```text
short audio → Stick
long markdown → Pi screen
```

The Stick only receives:

```text
"Details on Pi."
```
