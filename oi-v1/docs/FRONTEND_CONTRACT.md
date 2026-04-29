# Frontend Contract (Frozen Draft)

Status: draft-frozen for implementation kickoff
Owner package: WP-00

## Tooling/runtime commands (WP-00a outputs)

These are the authoritative commands for implementation agents.

- Run mock frontend scaffold (local reducer replay):
  - `npx tsx mock-device/src/main.ts --fixture tests/fixtures/pi-events/no-sessions.jsonl`
- Run mock device interactively:
  - `./scripts/pi-oi-mock`
  - `./scripts/pi-oi-mock --fixture tests/fixtures/pi-events/X.jsonl`
  - `./scripts/pi-oi-mock --pi-rpc`
  - `./scripts/pi-oi-mock --pi-rpc --pi-rpc-cmd "pi --mode rpc --no-session"`
  - `npx tsx mock-device/src/main.ts --interactive [--pi-rpc]`
- Run reducer + parser tests:
  - `npx tsx --test 'mock-device/tests/**/*.test.ts'`
- Run fixture replay directly:
  - `npx tsx mock-device/src/replay.ts tests/fixtures/pi-events/<fixture>.jsonl`

If command paths change during implementation, update this file in the same PR.

---

## Frontend state schema (minimum)

```yaml
FrontendState:
  view: idle|session_list|prompt|command_menu|settings
  sessions:
    active_session_id: string|null
    list:
      - session_id: string
        name: string
        status: string
        pending_count: int
        stale: bool
        last_seen_age_s: int|null
  prompt:
    pending: bool
    prompt_id: string|null
    session_id: string|null
    title: string|null
    body: string|null
    options: [ { label: string, value: string } ]
  queue_health:
    oldest_pending_prompt_age_s: int|null
    oldest_queued_command_age_s: int|null
  device_hint:
    response_pace_hint: string|null
  last_action_result:
    ok: bool
    code: string|null
    message: string|null
```

---

## Action catalog (payload/result/error)

## Session actions

### `session.list`
Payload: `{}`
Result: `{ sessions: SessionSummary[], active_session_id: string|null }`
Errors: `backend_unavailable`

### `session.focus`
Payload: `{ session_id: string }`
Result: `{ active_session_id: string }`
Errors: `session_not_found`, `backend_unavailable`

### `session.cycle`
Payload: `{ direction: "next"|"prev" }`
Result: `{ active_session_id: string|null }`
Errors: `backend_unavailable`

## Prompt actions

### `prompt.answer`
Payload: `{ prompt_id: string, value: string }`
Result: `{ status: "answered"|"ignored", prompt_id: string }`
Errors: `prompt_not_found`, `validation_error`, `backend_unavailable`

### `prompt.cancel`
Payload: `{ session_id?: string, dry_run?: boolean, reason?: string }`
Result: `{ cancelled: number, inspected: number, dry_run: boolean }`
Errors: `validation_error`, `backend_unavailable`

## Command actions

### `command.queue`
Payload:
```yaml
session_id: string
verb: status|abort|follow_up|steer|prompt|speak
args: object
request_id: string|null
expires_at: string|null
```
Result: `{ command_id: string, status: "queued"|"deduped" }`
Errors: `session_not_found`, `validation_error`, `backend_unavailable`

### `command.cancel`
Payload: `{ command_id: string, reason?: string }`
Result: `{ status: "cancelled"|"unchanged" }`
Errors: `command_not_found`, `backend_unavailable`

### `command.cancel_all`
Payload: `{ session_id?: string, reason?: string, dry_run?: boolean }`
Result: `{ cancelled: number, inspected: number, dry_run: boolean }`
Errors: `validation_error`, `backend_unavailable`

### `session.cleanup`
Payload: `{ session_id?: string, reason?: string, dry_run?: boolean }`
Result:
```yaml
cancel_prompts:
  cancelled: int
  inspected: int
cancel_commands:
  cancelled: int
  inspected: int
dry_run: bool
```
Errors: `validation_error`, `backend_unavailable`

## Operator actions

### `healthcheck`
Payload: `{ max_oldest_prompt_s?: int, max_oldest_command_s?: int, max_stale_sessions?: int }`
Result: `{ ok: bool, violations: string[] }`
Errors: `backend_unavailable`

---

## Interactive CLI controls (local scaffold)

The `pi-oi-mock` interactive CLI is a thin scaffold over the reducer actions listed above. Each keyboard command maps directly to a single action frame:

| Key | Action | Notes |
|-----|--------|-------|
| `n`/`p` | `session.cycle` | direction: next/prev |
| `f <id>` | `session.focus` | |
| `m` | snapshot toggle | switches `view` between `idle` and `command_menu` |
| `a <pid> <val>` | `prompt.answer` | |
| `c <verb> [json]` | `command.queue` | session defaults to active |
| `x <cmd_id>` | `command.cancel` | |
| `X [session] [--dry-run]` | `command.cancel_all` | |
| `k [session] [--dry-run]` | `session.cleanup` | session defaults to active |
| `h [jsonThresholds]` | `healthcheck` | thresholds parsed as JSON |
| `u` | sync-from-backend | requests `get_state` in Pi RPC mode; local mode prints guidance to start with `--pi-rpc` |
| `q` | quit | exits interactive loop |

## Local scaffold behavior notes

The mock-device TypeScript scaffold implements the actions above with these differences from a live backend:

- `command.cancel`: removes queued commands from local state immediately; returns `command_unchanged` for non-queued commands (no backend round-trip).
- `command.cancel_all`: filters local `queued_commands` by `status === "queued"`; `dry_run` returns counts without mutation.
- `session.cleanup`: removes pending prompts and queued commands (status `"queued"`) for the target session from local state; decrements `pending_count` on the session. `dry_run` returns counts without mutation.
- `healthcheck`: operates on `queue_health` and session `stale` fields already in local state (populated by snapshots/events). No backend call.

## Global behavior rules

1. `request_id` dedupe applies to queued command creation.
2. Single-command cancel is idempotent for finished commands (`unchanged`).
3. Destructive bulk actions (`prompt.cancel`, `command.cancel_all`, `session.cleanup`) must support `dry_run`.
4. UI must show `last_action_result` for every action attempt.

---

## Reconnect/resync rules

1. On transport reconnect, perform full snapshot sync before accepting new user actions.
2. If event order is ambiguous, snapshot data is authoritative.
3. If command/prompt ids disappear unexpectedly, trigger snapshot reconcile and clear stale local view entries.

---

## Workflow mapping (required v1)

| Workflow | Action sequence | Expected resulting state |
|---|---|---|
| Switch active session | `session.cycle` or `session.focus` | `sessions.active_session_id` updated; view remains `idle` or `session_list` |
| Approve/deny prompt | `prompt.answer` | `prompt.pending=false` for answered prompt after reconcile |
| Nudge/continue/summarize | `command.queue` (`verb=follow_up`, preset in `args`) | command appears queued/acked; `last_action_result.ok=true` |
| Stop/abort | `command.queue` (`verb=abort` or `verb=steer`) | active run transitions toward stopped/idle state |
| Speak output | `command.queue` (`verb=speak`) | queued/acked with visible action feedback |
| Cleanup pending work | `session.cleanup` (or `prompt.cancel` + `command.cancel_all`) | pending counts drop after reconcile |
| Health warning check | `healthcheck` | `ok=false` shows violation list when thresholds breached |

---

## Deferred from v1

- on-device voice/STT capture as mandatory workflow

## Transitional adapter: OI server-backed mode (removed)

`mock-device/src/oi_server.ts` and `--oi-server`/`--oi-token` CLI support were removed after Pi RPC transport landed.

This clears deprecation sequence item #1 from `docs/DEPRECATION_PLAN.md` for the mock frontend path.

---

## Pi RPC mode (implementation path)

The mock-device scaffold now has a Pi RPC transport adapter (`mock-device/src/pi_rpc.ts`) that enables interactive operation backed by a `pi --mode rpc --no-session` subprocess instead of HTTP.

- **Enabled by:** `--pi-rpc` flag on the interactive CLI, with optional `--pi-rpc-cmd <command>`.
- **Transport:** JSONL over stdin/stdout. Commands are sent as single JSON lines (`{ "type": "get_state" }`); responses and events arrive as LF-delimited JSON lines.
- **Initialisation:** `get_state` is sent on startup; the response seeds the reducer snapshot.
- **Command routing:** `status`, `abort`, `follow_up`, `steer`, `prompt` verbs are sent as RPC commands. `speak` stays local-only.
- **Extension prompts:** Incoming `extension_ui_request` messages (select/confirm/input/editor) map to reducer `prompt.pending` events. `prompt.answer` routes `extension_ui_response` back to the RPC process when the prompt originated there.
- **Sessions:** if `get_state` returns a `sessions` array + `active_session_id`, the reducer consumes it directly for multi-session rendering.
- **Sync:** Press `u` in interactive mode to send `get_state` and refresh from the RPC process.
