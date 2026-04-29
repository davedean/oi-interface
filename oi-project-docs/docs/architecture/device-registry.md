# Device Registry

## Purpose

The device registry exposes all devices and embodiments to the agent as a machine-readable capability tree.

Conceptually:

```text
/devices/stick-pocket
/devices/desktop-main
/devices/headphones
/devices/watch
/devices/kitchen-display
```

## Design goal

The agent should be able to reason about:

- what devices exist;
- what they can do;
- where the human probably is;
- which device is foreground;
- what each device should be allowed to do;
- which device should receive a given response.

## Example device document

```json
{
  "id": "stick-pocket",
  "type": "voice_terminal",
  "name": "Pocket Stick",
  "owner": "local-user",
  "online": true,
  "foreground_score": 0.82,
  "capabilities": {
    "input": ["hold_to_record", "button_confirm", "button_cancel"],
    "output": ["tiny_screen", "cached_audio", "status_character"],
    "sensors": ["battery", "wifi_rssi", "imu"]
  },
  "constraints": {
    "max_text_chars": 48,
    "audio_playback": "cached",
    "audio_streaming": false,
    "screen_width": 135,
    "screen_height": 240,
    "battery_sensitive": true
  },
  "attention": {
    "can_interrupt": false,
    "can_request_attention": true,
    "preferred_for": ["quick_voice", "status", "approval"],
    "never_for": ["long_text", "secret_display"]
  },
  "state": {
    "mode": "RESPONSE_CACHED",
    "battery_percent": 64,
    "wifi_rssi": -68,
    "muted_until": null,
    "last_interaction_at": "2026-04-27T04:33:00Z"
  },
  "theme": {
    "character_pack": "synth-goblin-v1"
  }
}
```

## Filesystem-like surface

Suggested paths:

```text
/devices
/devices/{id}/identity
/devices/{id}/capabilities
/devices/{id}/constraints
/devices/{id}/state
/devices/{id}/attention
/devices/{id}/theme
/devices/{id}/commands
/devices/{id}/events
```

Reads are broadly available to the chief agent. Writes happen through commands.

## Foreground detection

Signals:

- last human interaction time;
- device explicitly selected by user;
- device proximity if known;
- active desktop session;
- motion/IMU;
- audio route;
- calendar context;
- privacy policy.

Do not overfit this early. Start with "last interacted device wins for 10 minutes."

## Multiple embodiments

One chief agent may have many bodies. Subagents do not get their own embodiment by default.

The chief agent decides which output appears where.
