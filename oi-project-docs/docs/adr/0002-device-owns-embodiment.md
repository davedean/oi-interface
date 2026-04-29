# ADR 0002: Device owns embodiment

## Status

Proposed

## Context

The agent could theoretically control everything about the device, including button semantics. That is flexible but unsafe and confusing.

## Decision

The device firmware owns physical interaction grammar and local state safety.

The agent may request semantic actions such as `show thinking` or `cache response`, but it cannot redefine long-hold/double-tap semantics at runtime.

## Consequences

Good:

- reliable muscle memory;
- safer physical UX;
- easier firmware testing;
- less creepy behaviour;
- lower chance of agent-induced weirdness.

Bad:

- less dynamic customization;
- firmware updates needed for new physical gestures;
- some experiments require deeper device changes.

## Notes

This is the central safety split:

```text
agent owns intention
device owns embodiment
```
