# Vision

Agent Stick is a new interaction model for personal computing.

The near-term product is a tiny voice terminal that talks to a local agent server. The long-term product is a personal agent operating environment where computing is no longer centered on apps, screens, or devices. It is centered on a persistent agent that understands goals, owns context, delegates work, and appears through whatever surface is appropriate.

## The core inversion

Traditional computing:

```text
human chooses app → human performs task → app shows result
```

Agent Stick:

```text
human states intent → agent chooses method → devices show state and request control
```

The user no longer thinks, "Which app do I open?"  
They think, "Tell my agent what I want."

## Why now

Several things are converging:

- Tiny, cheap microcontrollers can provide always-near interaction surfaces.
- Local speech-to-text and text-to-speech are good enough for private local workflows.
- Agent runtimes can call tools, delegate to subagents, and persist across sessions.
- Self-hosted control planes are becoming normal for technical users.
- Users are increasingly uncomfortable with cloud assistants that record everything and do little.
- Existing interfaces are attention-heavy. Voice plus tiny status surfaces are lighter.

## The end-state

By 2030, the project should feel less like a gadget and more like a personal compute substrate:

- A persistent chief-of-staff agent knows active projects, preferences, permissions, and constraints.
- Multiple devices expose capabilities through a shared device registry.
- The agent routes responses to the right embodiment: tiny puck, desktop, phone, watch, web dashboard, terminal, car, headphones, room display.
- The user can inspect and edit the agent's memory through a personal wiki.
- Tool use is permissioned, logged, reversible where possible, and sandboxed.
- User-owned infrastructure is first-class.
- Cloud hosting is optional, portable, and replaceable.
- Third-party ecosystems can plug in without gaining unlimited authority.

## What "bigger than Google" means here

Not "build a bigger search engine."

The swing-for-the-fences idea is:

> Replace the app/search/browser-centered model of personal computing with a private, persistent, user-owned agent environment.

Search is only one tool. Apps are only one kind of tool. Devices are only embodiments.

The ambitious version becomes:

- a personal agent runtime;
- a safe tool economy;
- a device abstraction layer;
- an owned memory substrate;
- a marketplace of audited capabilities;
- a local-first alternative to platform-owned assistants;
- a new interaction grammar for ambient computing.

## Product sentence

Agent Stick is a local-first personal agent OS for tiny voice terminals and every device you already own.

## Technical sentence

Agent Stick is a device-agnostic agent runtime with a filesystem-like capability registry, a constrained wire protocol for embodied devices, a persistent chief-agent session, a permissioned tool broker, subagent delegation, human-reviewable memory, and local/remote deployment modes.

## Design motto

One mind. Many bodies. Human in control.
