# Integration: Hermes Agent

## Current understanding

Nous Research's Hermes Agent is a self-improving AI agent framework. Its README describes a learning loop, skill creation/improvement, long-term memory, cross-session recall, scheduled automations, subagents, multiple terminal backends, and support for channels such as Telegram, Discord, Slack, WhatsApp, Signal, and CLI.

## How Agent Stick should relate to Hermes Agent

Hermes Agent overlaps with the chief-agent/runtime layer.

There are three integration modes.

## Mode A: Hermes as a subagent backend

```text
Agent Stick chief agent
  → tool broker
    → hermes.run_task
```

Good for:

- coding tasks;
- research;
- skill-learning experiments;
- long-running cloud/VPS tasks.

Agent Stick remains the user-facing coordinator.

## Mode B: Hermes as the chief agent

```text
Device gateway
  → Hermes Agent
    → Agent Stick device adapter
```

Good for rapid experimentation if Hermes already provides persistence, memory, channels, and subagents.

Risk: Agent Stick may lose control over interaction policy and device embodiment semantics unless the adapter is strict.

## Mode C: Shared memory/tool ecosystem

Agent Stick and Hermes share:

- MCP tools;
- wiki documents;
- task artifacts;
- selected memory summaries.

This is useful but needs conflict control.

## Adapter contract

Example tool:

```json
{
  "tool": "hermes.delegate",
  "risk": "medium",
  "args": {
    "goal": "Assess this repo change",
    "context_refs": ["wiki://projects/agent-stick.md", "repo://agent-stick"],
    "permissions": ["repo.read"],
    "output_contract": "assessment_report_v1"
  }
}
```

## Learning-loop caution

A self-improving agent that creates and improves skills is powerful. It should not be allowed to silently create new privileged capabilities.

Policy:

- learned skills start untrusted;
- skills can be proposed, not automatically installed into privileged contexts;
- human review required for persistent skills;
- tool broker gates learned skill execution.

## Best early use

Use Hermes as a delegated worker, especially for tasks where its memory/skill loop is useful, while Agent Stick owns devices, routing, and approvals.

## Oi Gateway channel model

Hermes Agent can be treated as another backend brain.

```text
Oi device/app
  → oi-gateway
    → Hermes adapter
      → Hermes Agent
```

If Hermes exposes a channel/message endpoint, Oi can inject wrist/earbud/tiny-device context in the same way as the OpenClaw plugin.

For example:

```text
This message came from Oi via Apple Watch and AirPods.
Keep response brief and suitable for private spoken playback.
```

Hermes can also be used as a delegated worker behind a local Oi chief agent.
