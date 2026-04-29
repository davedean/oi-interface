# Human Interaction Spec

## Primary interaction

The current model is the default:

```text
long-hold → speak
release → submit
agent works
response cached
double-tap → listen
```

## Why cached response

Cached playback keeps the human in control.

The device does not suddenly talk. It signals that a response is ready. The human asks to hear it.

This is especially important for:

- shared spaces;
- sensitive content;
- night use;
- work contexts;
- avoiding uncanny assistant behaviour.

## Button grammar

Required:

```text
Long-hold:
  Start recording.

Release:
  Stop recording and submit.

Double-tap:
  Play latest cached response.

Tap while playing:
  Stop playback.

Very-long-hold:
  Toggle local mute or safe mode.

Optional:
  Triple-tap:
    repeat status without audio;
  shake:
    cancel speech;
  button chord:
    pairing/recovery.
```

## Spoken response style

Default spoken responses should be short.

Good:

```text
Done.
Muted for 30 minutes.
I'm checking that now.
Looks viable, but I need approval before changing files.
I found one risk. Details are on your desktop.
```

Bad:

```text
Certainly! I have initiated an extensive analysis of your project architecture and will now provide a detailed explanation...
```

## Interaction states

User-visible states:

- ready;
- listening;
- uploading;
- thinking;
- response ready;
- playing;
- muted;
- offline;
- needs approval;
- error.

Every state should be visible without reading a paragraph.

## Confirmation UX

Risky actions must be confirmable on multiple surfaces.

Tiny device confirmation:

```text
Apply patch?
A yes / B no
```

Desktop confirmation:

- full diff;
- risk summary;
- rollback plan;
- approve/deny.

Voice confirmation:

```text
"Yes, apply it."
```

But voice-only confirmation should be avoided for high-risk actions unless the user explicitly enables it.

## Interruptions

The agent should not interrupt by speaking unless the device's attention profile allows it.

Levels:

```text
silent:
  update status only

request_attention:
  show ready/blocked state

soft_interrupt:
  beep or haptic

speak:
  play audio automatically

urgent:
  use multiple channels
```

The M5Stick default is `request_attention`, not `speak`.

## "What are you doing?"

This is a first-class command.

Response example:

```text
I’m doing two things:
1. Checking the repo retry change. Tests are running.
2. Waiting for your approval to save a wiki note.
```

## Error UX

Errors should be plain.

```text
I lost Wi-Fi.
I couldn't reach the home server.
The repo tool is locked until you approve it.
The audio response was too large for the device cache.
```

## Privacy UX

The device must make recording obvious.

No hidden recording.

Recommended indicators:

- screen state;
- icon/character listening state;
- optional LED;
- optional short tone at recording start/end.

## Multi-device UX

Rules:

- last interacted device is foreground for a short window;
- only one device should speak by default;
- status may mirror to multiple devices;
- sensitive content goes only to private devices;
- confirmations can appear on multiple devices;
- user can say "answer here" or "send it to desktop."
