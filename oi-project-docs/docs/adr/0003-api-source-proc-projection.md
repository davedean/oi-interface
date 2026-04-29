# ADR 0003: API source of truth, proc tree projection

## Status

Proposed

## Context

A proc-style filesystem is a powerful metaphor for agents and humans. Devices and capabilities could appear under paths such as `/devices/oi-stick/state`.

But devices need reliable registration, authentication, streaming, acknowledgements, and reconnect semantics.

## Decision

Use API/events as the source of truth.

Expose a proc-style resource tree as a projection.

## Consequences

Good:

- transport is reliable and versioned;
- agents get a stable inspectable tree;
- humans get a debuggable CLI/FUSE path later;
- commands remain validated and policy-controlled.

Bad:

- more implementation layers;
- the proc view must stay consistent with backend state.

## Implementation order

```text
internal resource graph
HTTP API
watch API
CLI
agent tools
optional FUSE
```
