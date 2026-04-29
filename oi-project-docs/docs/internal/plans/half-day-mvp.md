# Half-day MVP

## Goal

Demonstrate the core interaction loop end-to-end using existing working pieces.

## Success criteria

A user can:

1. long-hold the Stick and say "mute yourself for 30 minutes";
2. see the device enter thinking/status state;
3. receive a cached spoken response;
4. double-tap to play it;
5. ask "what are you doing?";
6. get a useful short answer;
7. inspect logs on the server.

## Scope

Use current Python where possible.

Do not solve:

- generated character packs;
- multi-device routing;
- hosted relay;
- complex permissions;
- OpenClaw/Hermes integration;
- repo-writing agents.

## Components

### Device

- keep current long-hold record;
- keep current double-tap playback;
- add simple state labels;
- expose basic state JSON:
  - mode;
  - battery if easy;
  - Wi-Fi RSSI if easy;
  - cache status;
  - muted until.

### Server

- receive audio;
- run Whisper or current STT;
- route transcript to simple agent;
- run Piper or current TTS;
- send audio back to device cache;
- keep event log in SQLite or JSONL.

### Agent

Hardcode or prompt-tool:

- `device.mute_until`;
- `device.set_brightness`;
- `task.list_active`;
- `todo.add`.

## Implementation steps

1. Create `gateway.py`.
2. Define minimal JSON messages.
3. Add `events.jsonl`.
4. Add `device_state.json`.
5. Add `agent_loop.py`.
6. Add two tools:
   - mute;
   - brightness.
7. Add "what are you doing?" response.
8. Add README instructions.

## Demo script

```text
Human: long-hold
Human: mute yourself for thirty minutes
Device: thinking
Device: response cached
Human: double-tap
Device: "Muted until 3:14 PM."
Human: long-hold
Human: what are you doing?
Device: response cached
Human: double-tap
Device: "I'm muted until 3:14 PM. No other tasks are running."
```

## Non-negotiable UX

- no auto-speaking;
- recording visually obvious;
- local mute works;
- logs visible.
