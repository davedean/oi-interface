# Security Model

## Threat assumptions

Assume:

- model output can be wrong;
- prompts can be malicious;
- documents can contain prompt injection;
- third-party skills can be hostile;
- devices can be lost;
- local networks can be weird;
- OAuth tokens are high-value;
- users will accidentally over-grant permissions if the UI is too smooth.

## Assets

- user identity;
- local files;
- repos;
- secrets;
- OAuth tokens;
- email/calendar/messages;
- home automation controls;
- personal wiki/memory;
- device microphone;
- audit log;
- agent permissions.

## Trust zones

```text
Zone 0: Device firmware
  trusted for local input semantics, not for secrets beyond pairing token.

Zone 1: Gateway
  trusted transport/control plane.

Zone 2: Agent runtime
  semi-trusted reasoning system, not a security boundary.

Zone 3: Tool broker
  security boundary.

Zone 4: Sandboxed tools/subagents
  constrained.

Zone 5: Third-party skills
  untrusted until audited.
```

## Principle

The model is not a permission system.

## Required controls

- explicit device pairing;
- token revocation;
- per-tool permission checks;
- confirmation UX;
- audit log;
- sandboxed third-party skills;
- least-privilege credentials;
- no ambient shell for the chief agent;
- secret redaction;
- prompt injection warnings for untrusted documents;
- ability to stop all tasks.

## Device loss

A lost device should be revocable.

Device should not contain:

- model API keys;
- long-lived OAuth tokens;
- plaintext private notes;
- unrestricted server credentials.

It may contain:

- device identity;
- session token with expiry;
- cached audio response, if accepted by user policy.

## Third-party ecosystem

Open skill ecosystems are useful and dangerous.

Any integration with OpenClaw skills, MCP servers, Hermes tools, or user-contributed plugins must go through:

- source provenance;
- code inspection or signing;
- sandbox;
- limited credentials;
- install confirmation;
- audit.

## Remote access

For remote access:

- prefer Tailscale/WireGuard first;
- hosted relay should be end-to-end encrypted where possible;
- remote commands can carry higher risk scores;
- require step-up confirmation for sensitive tasks.

## Kill switches

User commands and device gestures:

```text
stop all tasks
revoke tools
mute all devices
safe mode
disconnect this device
forget current session
```

## Logging

Logs should be useful but privacy-aware.

Separate:

- operational logs;
- audit logs;
- transcripts;
- secret-bearing tool outputs;
- user-visible history.

## Security UX

Show what matters:

```text
OpenClaw skill requests filesystem and shell access.
Allow once / deny / inspect
```

Not:

```text
Permission scope: com.agent.runtime.capability.execution.host.system.full
```
