# Integration: MCP

## Purpose

Model Context Protocol-style tools are a natural way to expose services to agents.

Agent Stick should support MCP servers, but not treat MCP as a complete safety model.

## Position

```text
MCP server
  → capability adapter
    → tool broker
      → chief agent/subagents
```

## Rules

- MCP tools are imported as capabilities.
- Every imported tool gets a risk class.
- Permissions are enforced by the Agent Stick tool broker.
- MCP server credentials are scoped.
- Third-party MCP servers are untrusted until reviewed.

## Example

```json
{
  "capability": "github.issue.create",
  "source": "mcp:github",
  "risk": "medium",
  "requires_confirmation": true,
  "allowed_repos": ["owner/agent-stick"]
}
```

## Good MCP use cases

- GitHub;
- filesystem read/write in scoped directories;
- calendar;
- browser automation;
- database read-only queries;
- issue trackers;
- docs search.

## Dangerous MCP use cases

- unrestricted shell;
- unrestricted filesystem;
- browser with logged-in sessions;
- secrets manager raw access;
- email send;
- payment/purchasing tools.

## Implementation plan

1. Add MCP client support behind tool broker.
2. Import tool schemas.
3. Let admin classify risks.
4. Default unknown tools to confirm/deny.
5. Log every invocation.
