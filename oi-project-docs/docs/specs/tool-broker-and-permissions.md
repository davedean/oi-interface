# Tool Broker and Permissions

## Purpose

The tool broker is the safety boundary between agents and the world.

Agents propose actions. The broker decides whether and how actions execute.

## Core rule

No agent directly executes side-effecting tools.

## Permission classes

```text
read_public:
  public web/search/docs

read_private:
  user's files, email, calendar, repos

write_low:
  create note, add todo, change device brightness

write_medium:
  edit wiki, draft email, create branch, run tests

write_high:
  send email, modify repo, home automation, spend money

dangerous:
  delete data, install software, run arbitrary shell, unlock doors, expose secrets
```

## Tool invocation envelope

```json
{
  "request_id": "toolreq_123",
  "actor": "chief",
  "delegated_to": "repo_assessor",
  "tool": "repo.apply_patch",
  "risk": "medium",
  "reason": "Implement approved retry backoff change",
  "args": {
    "repo": "agent-stick",
    "branch": "agent/retry-backoff",
    "patch_ref": "patch_123"
  },
  "dry_run": false,
  "requires_confirmation": true,
  "rollback": {
    "type": "git_branch_delete",
    "branch": "agent/retry-backoff"
  }
}
```

## Confirmation policy

Require confirmation for:

- external communication;
- repo writes;
- shell commands outside sandbox;
- purchases;
- destructive operations;
- persistent permission grants;
- third-party skill installation;
- memory changes marked important;
- home automation actions with safety implications.

## Audit log

Every tool call records:

- timestamp;
- actor;
- input;
- permission decision;
- confirmation id if any;
- result;
- stdout/stderr summary;
- artifact refs;
- rollback plan;
- model/session id if relevant.

## Skill sandboxing

Third-party skills should run in constrained environments:

- container/VM/process sandbox;
- no ambient credentials;
- explicit input/output;
- no direct filesystem except mounted workspace;
- network policy;
- timeouts;
- resource limits;
- audit logging.

## Capability grants

Avoid blanket permissions.

Prefer:

```text
repo.read:~/src/agent-stick for 30 minutes
calendar.read for this request
email.draft only, no send
home.light.write living-room only
```

## Local policy file

Example:

```yaml
defaults:
  send_email: confirm
  repo_apply_patch: confirm
  device_brightness: allow
  device_mute: allow
  shell_exec: confirm_high
  third_party_skill_install: deny

trusted_tools:
  - wiki.append_inbox
  - todo.add
  - device.set_brightness

dangerous_tools:
  - shell.exec
  - browser.cookies.read
  - secrets.read
```

## Human commands

```text
revoke tools
what can you access?
why do you need that permission?
show recent tool use
approve this once
always allow this for this project
never allow that
```

## Security posture

Assume agents are fallible. Assume third-party skills may be hostile. Assume prompts can be malicious. Design so one bad tool call is contained.
