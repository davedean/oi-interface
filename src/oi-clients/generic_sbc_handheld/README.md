# Oi Generic SBC Handheld Target

**Status:** active sketch

Plain English: this is the promising path for retro handhelds like the **RG35XXSP**.

Unlike PICO-8, these devices can often run normal Linux user-space code with:
- Wi-Fi
- gamepad/button input
- local audio output
- optional USB microphone support

That means we can build something much closer to a real Oi device target without heroic workarounds.

## What this target is

This is **not bare-metal firmware**.

It is a **small Linux-side device runtime** that behaves like Oi firmware from the gateway's point of view:
- connects to `oi-gateway`
- speaks DATP directly
- sends button/input events
- renders a tiny local UI
- optionally records audio from a USB mic
- optionally plays TTS/audio replies on-device

## Why this is better than the PICO-8 path

- direct networking is available
- Python is viable
- audio input/output can use standard Linux stacks
- one codebase can cover many handhelds
- launcher packaging can be platform-specific later, while the core runtime stays generic

## Target devices

Initial design target:
- **RG35XXSP** with Wi-Fi and optional USB mic

Broader class:
- Linux-based retro handhelds / SBC consoles
- devices with small screens and gamepad-like input
- devices where we can launch a user-space app at boot or from a launcher

## Product shape

Think of this as an **embodied handheld Oi terminal**:
- short responses
- button-first interaction
- readable tiny-screen cards
- optional press-to-talk or accessory mic flow

## Files in this sketch

- `GENERIC_SBC_HANDHELD_PLAN.md` — architecture and phased plan
- `capability-profile.json` — draft capability shape for gateway registration
- `runtime_sketch.py` — illustrative Linux user-space runtime skeleton

## Key implementation insight from `oi-sim`

Plain English: the future SBC client should probably be built by **reusing the protocol brain from `oi-sim`** and replacing only the front-end.

What `oi-sim` already gives us:
- a user-space DATP device model
- WebSocket connect + `hello` / `hello_ack` flow
- capabilities/state reporting shape
- command receive/track behavior
- a device state machine matching the firmware/device model

What the SBC target still needs on top:
- real gamepad/button input adapters
- a tiny handheld renderer instead of the sim REPL
- audio capture/playback adapters for Linux
- packaging/launcher integration for handheld distros

Best mental model:
- `oi-sim` = protocol/device behavior reference
- `generic_sbc_handheld` = same behavior, but with real handheld I/O

## Core idea

```text
buttons/gamepad + tiny ui + mic/speaker
                 │
                 ▼
┌────────────────────────────────────┐
│ generic sbc handheld runtime       │
│ - DATP client                      │
│ - input adapter                    │
│ - tiny UI renderer                 │
│ - audio capture/playback           │
│ - reconnect/state reporting        │
└────────────────────────────────────┘
                 │
                 ▼
            oi-gateway
```

## Non-goals for the first pass

- perfect support for every handheld distro
- production packaging for all launcher ecosystems
- freeform text entry as a primary UX
- hardware-specific optimizations before proving the generic path
