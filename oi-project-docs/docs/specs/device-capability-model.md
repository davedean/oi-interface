# Device Capability Model

## Purpose

A capability model lets the agent reason about devices without hardcoding device types.

## Capability document

```json
{
  "device_id": "stick-pocket",
  "protocol": "datp",
  "capabilities": {
    "audio_input": {
      "modes": ["hold_to_record"],
      "formats": ["pcm16"],
      "sample_rates": [16000],
      "streaming": true,
      "max_recording_seconds": 60
    },
    "audio_output": {
      "modes": ["cached_playback"],
      "formats": ["wav_pcm16"],
      "sample_rates": [22050],
      "max_cache_bytes": 2097152,
      "slots": 4
    },
    "display": {
      "type": "tiny_color",
      "width": 135,
      "height": 240,
      "comfortable_chars": 48,
      "supports_character_pack": true
    },
    "buttons": {
      "events": ["tap", "double_tap", "long_hold", "very_long_hold"],
      "firmware_owned_semantics": true
    },
    "power": {
      "battery": true,
      "charging": true
    }
  }
}
```

## Capability categories

### Input

- button events;
- audio recording;
- text input;
- touchscreen;
- keyboard;
- sensor events.

### Output

- tiny screen;
- full screen;
- cached audio;
- streaming audio;
- haptics;
- notification;
- LED/status light.

### Sensors

- battery;
- Wi-Fi/RSSI;
- location if available;
- proximity;
- IMU;
- microphone level;
- ambient light.

### System

- reboot;
- firmware update;
- diagnostics;
- storage info;
- pairing;
- safe mode.

## Constraints

Capabilities must include constraints.

Examples:

- max text length;
- supported audio format;
- maximum cache size;
- can interrupt user;
- can speak autonomously;
- network path;
- privacy level.

## Semantic affordances

Devices should declare what they are good for:

```json
{
  "preferred_for": [
    "quick_ack",
    "voice_query",
    "approval",
    "status_glance"
  ],
  "avoid_for": [
    "long_form_reading",
    "secret_display",
    "large_diff_review"
  ]
}
```

## Capability versioning

Each capability has:

- name;
- version;
- schema;
- optional extensions;
- graceful fallback.

Example:

```text
display.status_card.v1
audio.cached_playback.v1
input.button_confirm.v1
```
