# Design Principles

## 1. The device owns embodiment

The device owns buttons, screen, audio cache, mute, local safety, and recovery.

The agent may request. The firmware decides whether a request is legal.

## 2. The agent owns intention

The agent decides what the user probably wants, whether to delegate, whether to ask, and where to reply.

It should not own raw hardware semantics.

## 3. Human attention is scarce

Default to:

- short spoken responses;
- cached playback, not forced playback;
- explicit confirmation for risky work;
- screen status over interruptions;
- richer detail delivered to richer surfaces.

## 4. Local-first by default

Home server first. Tailscale/WireGuard for remote access. Hosted options later.

Cloud models and hosted relays are optional, visible, and replaceable.

## 5. Capabilities over apps

Devices and services expose capabilities. The agent composes them.

Avoid hardcoded "apps" as the primary abstraction.

## 6. Every risky action has a boundary

Shell, email, repo writes, purchases, deletion, smart locks, OAuth scopes, and third-party skills must pass through a permission broker.

## 7. Memory must be inspectable

The canonical memory should be human-editable documents and structured state, not just opaque embeddings.

## 8. Explain state, not internals

The user should always be able to ask:

- What are you doing?
- What are you waiting on?
- What did you change?
- Why are you asking?
- What devices can hear or speak right now?

## 9. Boring firmware, weird agent

The agent can be experimental. The firmware should be predictable.

## 10. No fake omniscience

The system should expose uncertainty, missing context, offline state, and permission boundaries plainly.
