# Glossary

## Chief agent

The persistent primary interaction partner. It interprets intent, owns conversational continuity, manages tasks, delegates to subagents, and decides when to ask the human.

## Subagent

An ephemeral or scoped worker launched by the chief agent. Examples: code assessment agent, calendar agent, wiki agent, home automation agent.

## Embodiment

A concrete device or UI surface through which the agent can interact: M5Stick, desktop overlay, web dashboard, phone, watch, headphones, terminal, room display.

## Device

A physical or virtual endpoint that exposes capabilities and state.

## Device registry

The machine-readable tree of available devices, capabilities, state, constraints, and attention policies.

## Capability

A bounded thing a device or service can do: record audio, play cached response, show card, send email draft, run test command, query calendar.

## Tool broker

The only component allowed to invoke side-effecting tools. It enforces permissions, logging, dry-run, sandboxing, and confirmations.

## Task ledger

Durable event log and task state store. It records user requests, agent decisions, tool calls, results, and pending actions.

## Character pack

A visual status theme for embodied agent state. It maps semantic states such as idle/listening/thinking/blocked to sprites, animation hints, sounds, and colours.

## DATP

Device Agent Transport Protocol. A proposed wire protocol between devices and the gateway.

## App protocol

The higher-level protocol above DATP: states, commands, tasks, confirmations, cards, and device routing.

## Local-first

A deployment posture where the user's own hardware remains the primary system of record and control point.
