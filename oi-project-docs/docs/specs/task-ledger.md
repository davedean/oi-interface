# Task Ledger

## Purpose

The task ledger is the durable operational memory of the system.

It records what the user asked for, what the agent decided, what is running, what is blocked, and what changed.

## Why not just conversation history?

Conversation history is not enough.

The agent needs structured state:

- active tasks;
- blockers;
- delegated subagents;
- tool calls;
- confirmations;
- outputs;
- retries;
- schedules;
- failure state.

## Task states

```text
new
triaged
running
waiting_for_tool
waiting_for_human
blocked
completed
cancelled
failed
superseded
```

## Task schema

```json
{
  "id": "task_001",
  "title": "Assess retry worker change",
  "source": {
    "device_id": "stick-pocket",
    "utterance_id": "utt_123"
  },
  "state": "running",
  "priority": "normal",
  "risk": "medium",
  "created_at": "2026-04-27T04:50:00Z",
  "updated_at": "2026-04-27T04:52:00Z",
  "owner": "chief",
  "delegations": [
    {
      "subagent_id": "subagent_repo_001",
      "goal": "Read-only viability assessment",
      "state": "running"
    }
  ],
  "human_summary": "Checking whether retry worker change is viable.",
  "next_action": "Wait for test results",
  "artifacts": [],
  "confirmations": [],
  "tool_calls": []
}
```

## Event log

Each task has events:

```json
{
  "task_id": "task_001",
  "event_id": "taskevt_001",
  "type": "subagent_started",
  "ts": "2026-04-27T04:51:00Z",
  "summary": "Started repo assessor with read-only access."
}
```

## Query examples

- active tasks;
- blocked tasks;
- tasks waiting for human;
- tasks created from device;
- recent tool calls;
- tasks touching repo X;
- tasks with uncommitted artifacts.

## User-facing command

```text
what are you doing?
```

Queries task ledger.

```text
cancel the repo task
```

Cancels task and attempts rollback if needed.

```text
resume the thing about retries
```

Searches ledger and wiki.

## Storage

SQLite is sufficient initially.

Tables:

- tasks;
- task_events;
- delegations;
- confirmations;
- tool_calls;
- artifacts;
- schedules.

## Bigger version

The task ledger becomes the agent's process table.

Like `ps`, but for intentions.
