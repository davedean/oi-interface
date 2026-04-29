# Agent Runtime

## Goal

The agent runtime hosts the persistent chief agent, manages subagents, keeps task state durable, and provides controlled access to capabilities.

## Chief agent contract

The chief agent must be able to answer these questions at all times:

- What did the human ask?
- What tasks are active?
- What are you doing right now?
- What are you waiting on?
- Which devices are active?
- Which tool permissions are currently granted?
- What needs human confirmation?
- What changed since the last report?

## Agent loop

Pseudo-flow:

```text
receive event
  classify event
  update task ledger
  inspect device/attention state
  retrieve relevant memory
  decide:
    - respond immediately
    - ask clarification
    - delegate
    - schedule
    - request permission
    - refuse
  route output
  persist summary
```

## Persistent state

Suggested stores:

- SQLite for task ledger, events, permissions, devices, queue;
- Markdown files for canonical wiki;
- object storage or filesystem for audio blobs;
- vector index for retrieval, rebuilt from canonical sources;
- append-only logs for audit.

## Subagent model

Subagents should be scoped:

```json
{
  "id": "subagent-2026-04-27-001",
  "type": "repo_assessor",
  "goal": "Assess retry worker change viability",
  "input_context": ["repo:path", "wiki:project-note"],
  "permissions": ["repo.read", "test.readonly"],
  "time_budget_seconds": 600,
  "output_contract": "assessment_report_v1"
}
```

Subagents do not talk to humans directly unless explicitly assigned an embodiment.

## Session compaction

The chief agent will need compaction. Compaction must produce:

- active tasks;
- recent user preferences;
- pending confirmations;
- current device states;
- tool grants;
- unresolved errors;
- short narrative summary;
- links to canonical notes.

Compaction should never be the only store of truth.

## Restart semantics

"New agent" should mean:

- start a fresh model session;
- load durable state;
- preserve task ledger;
- preserve permissions according to policy;
- preserve user wiki;
- expose restart in audit log.

It should not mean losing the whole world.

## Agent self-inspection command

The human should be able to ask:

```text
what are you doing?
```

Required response shape:

```text
I am doing N things:
1. Task title — state — next action.
2. Task title — blocked by X.
3. Waiting for your approval on Y.
```

## Routing output

The chief agent decides output targets based on:

- foreground device;
- content sensitivity;
- length;
- modality;
- interruption policy;
- user preference;
- task urgency;
- device capability;
- privacy context.

Examples:

- short acknowledgement → Stick cached audio;
- long plan → dashboard/wiki plus short Stick summary;
- code diff → desktop;
- risky approval → Stick buttons plus dashboard detail;
- private message → user's private device only.
