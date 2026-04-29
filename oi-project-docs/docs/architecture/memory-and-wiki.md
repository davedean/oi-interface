# Memory and Wiki

## Goal

The system should remember useful things without becoming an opaque hallucinated diary.

## Memory layers

### 1. Event log

Raw-ish chronological record:

- transcripts;
- user commands;
- agent decisions;
- device events;
- tool calls;
- confirmations;
- errors.

Append-only.

### 2. Task ledger

Structured active and historical work.

### 3. Working memory

Compacted context used by the chief agent.

Regeneratable from durable stores.

### 4. Personal wiki

Human-readable canonical knowledge.

Markdown with frontmatter is the preferred starting point.

### 5. Retrieval index

Embeddings or search index built from canonical sources.

Never the source of truth.

## Wiki example

```markdown
---
type: project
status: active
owner: daewoo
related_repos:
  - ~/src/agent-stick
---

# Agent Stick

## Current interaction model

Long-hold records input. Double-tap plays cached response.

## Design preferences

- Local-first.
- Explicit attention.
- Tiny screen for status, not reading.
- Agent may delegate but must explain active tasks.
```

## Agent updates to wiki

Agent-generated updates should be proposed as diffs for important notes.

Low-risk append-only notes can be allowed under policy.

Example workflow:

```text
agent proposes note → user approves → wiki commit created → retrieval index rebuilt
```

## Memory safety

Avoid:

- treating inferred preference as fact;
- hiding memory updates;
- storing secrets in notes;
- letting third-party skills write memory directly;
- unbounded autobiographical accumulation.

## Commands

Useful user commands:

```text
remember that ...
forget that ...
show what you know about ...
why do you think that?
open the note for ...
summarize my current projects
```

## File layout

```text
wiki/
  inbox/
  people/
  projects/
  devices/
  preferences.md
  permissions.md
  daily/
```

## Bigger idea

The personal wiki is the owned substrate of the agent. The model session is temporary. The wiki is durable.
