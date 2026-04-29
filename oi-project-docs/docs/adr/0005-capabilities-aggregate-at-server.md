# ADR 0005: Capabilities aggregate at the server

## Status

Proposed

## Context

Devices can add meaningful capabilities to the system. A Raspberry Pi screen adds rich display. An iPhone with AirPods adds private mobile audio. A Watch adds haptics and quick confirmation.

The question is whether devices need to know the whole graph.

## Decision

Devices advertise local capabilities. The server aggregates effective system capabilities.

Devices do not need full system knowledge.

## Consequences

Good:

- simple device firmware;
- smarter server routing;
- dynamic capability graph;
- supports many form factors;
- avoids device-to-device coupling.

Bad:

- server is central coordinator;
- server needs good routing and presence logic.

## Rule

Devices emit events.  
Server/policy routes actions.  
Agents decide intent.
