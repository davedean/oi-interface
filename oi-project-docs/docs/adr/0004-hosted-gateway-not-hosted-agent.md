# ADR 0004: Hosted gateway, not hosted agent

## Status

Proposed

## Context

A hosted service could run the whole agent, but that creates privacy, liability, and differentiation problems. Many users will already have OpenClaw, Hermes, or another agent backend.

## Decision

Hosted Oi Gateway is primarily a relay/channel bridge.

It connects Oi apps/devices to existing agent systems.

## Consequences

Good:

- easier to sell;
- lower liability;
- works with existing agent ecosystems;
- preserves local-first ethos;
- clear recurring value for relay/push/channel service.

Bad:

- value depends on backend integrations;
- not a full solution for users without an agent;
- support matrix grows with agent ecosystems.

## Product sentence

Talk to your agent from your wrist, phone, earbuds, or tiny device without setting up Telegram or exposing your home server.
