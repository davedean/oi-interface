# ADR 0001: One mind, many bodies

## Status

Proposed

## Context

The system may support many devices: M5Stick, desktop, phone, watch, headphones, room display, terminal. It would be tempting to treat each as a separate assistant.

## Decision

There is one primary chief-agent session by default. Devices are embodiments of that session.

Subagents do not get user-facing embodiments unless explicitly routed through the chief agent.

## Consequences

Good:

- coherent memory;
- fewer conflicting assistants;
- simpler user mental model;
- central permission policy;
- better task continuity.

Bad:

- chief agent can become bottleneck;
- routing policy becomes important;
- multi-user households need careful extension.

## Notes

This does not prevent multiple users or multiple agents later. It sets the default for personal mode.
