# Device Runtime

## Purpose

The device runtime is firmware or a small local client that turns physical hardware into a deterministic agent embodiment.

It is not an agent.

## Responsibilities

- manage physical inputs;
- maintain local state machine;
- stream or upload audio;
- cache audio responses;
- play audio on user gesture;
- render small status UI;
- expose health state;
- validate commands;
- reconnect safely;
- fail closed.

## M5Stick first target

Initial hardware:

- M5Stack StickS3 or similar ESP32-S3 device;
- mic input;
- small colour screen;
- speaker or buzzer/audio output;
- buttons;
- Wi-Fi;
- battery;
- IMU if available.

## Firmware state machine

Required states:

```text
BOOTING
PAIRING
READY
RECORDING
UPLOADING
THINKING
RESPONSE_CACHED
PLAYING
MUTED
OFFLINE
ERROR
SAFE_MODE
```

### Legal transitions

```text
BOOTING -> PAIRING | READY | OFFLINE
PAIRING -> READY | ERROR
READY -> RECORDING
READY -> MUTED
READY -> OFFLINE
RECORDING -> UPLOADING
UPLOADING -> THINKING
THINKING -> RESPONSE_CACHED | READY | ERROR
RESPONSE_CACHED -> PLAYING
PLAYING -> RESPONSE_CACHED | READY
ANY -> SAFE_MODE
ANY -> ERROR
OFFLINE -> READY
```

The firmware should reject impossible transitions.

## Local interaction grammar

Hardcoded physical semantics:

```text
long-hold button:
  start recording

release after recording:
  stop recording and submit

double-tap:
  play latest cached response

tap during playback:
  stop playback

very-long-hold:
  local mute/safe mode

boot button chord:
  pairing or recovery mode
```

The agent must not dynamically redefine these gestures.

## Local persistence

The device should persist:

- device id;
- pairing credential;
- firmware version;
- last cached audio response if storage allows;
- mute state;
- brightness;
- last known gateway address;
- crash counter.

## Command validation

Every incoming command is checked against:

- protocol version;
- authentication;
- current mode;
- capability availability;
- argument bounds;
- rate limits;
- memory/storage limits.

## Local fallback

When disconnected:

- show OFFLINE;
- retain last cached response;
- allow playback;
- allow local mute/unmute;
- optionally queue one short recording if storage allows;
- attempt reconnection with backoff;
- never pretend the agent is available.

## Recommended implementation

Start with current Python/prototype on the server. For device firmware, move toward:

- ESP-IDF C/C++ for control and reliability;
- M5Unified if helpful for display/buttons;
- WebSocket client for DATP;
- I2S or device-specific audio capture/playback;
- ring buffers for audio;
- watchdog enabled;
- crash logs sent after reconnect.
