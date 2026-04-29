/**
 * Pi RPC Event Projections
 *
 * Implements all 16 Pi RPC event types as pure state-mutation projections.
 * Each projection is a pure function: (state, msg) => newState
 *
 * Unknown event types or sub-fields are tolerated: the reducer logs once and
 * returns state unchanged. Projection functions themselves have no side effects.
 *
 * Reference: docs/pi_rpc_protocol_inventory.json
 */

import type {
  LastActionResult,
} from "./types.ts";
import type {
  ExtendedFrontendState,
  ToolOutput,
  ToolExecution,
  ExtensionError,
} from "./pi_rpc_event_types.ts";
import {
  projectMessageStart,
  projectMessageUpdate,
  projectMessageEnd,
} from "./pi_rpc_message_projections.ts";

// ── EVENT_PROJECTIONS ────────────────────────────────────────────────────────

export const EVENT_PROJECTIONS: Record<string, (state: unknown, msg: unknown) => unknown> = {
  // Agent lifecycle events
  "agent_start": projectAgentStart,
  "agent_end": projectAgentEnd,

  // Turn lifecycle events
  "turn_start": projectTurnStart,
  "turn_end": projectTurnEnd,

  // Message lifecycle events
  "message_start": projectMessageStart,
  "message_update": projectMessageUpdate,
  "message_end": projectMessageEnd,

  // Tool execution lifecycle events
  "tool_execution_start": projectToolExecutionStart,
  "tool_execution_update": projectToolExecutionUpdate,
  "tool_execution_end": projectToolExecutionEnd,

  // Queue events
  "queue_update": projectQueueUpdate,

  // Compaction events
  "compaction_start": projectCompactionStart,
  "compaction_end": projectCompactionEnd,

  // Auto-retry events
  "auto_retry_start": projectAutoRetryStart,
  "auto_retry_end": projectAutoRetryEnd,

  // Extension events
  "extension_error": projectExtensionError,
};

// ── Log-once utility (used by reducer for unknown event types) ───────────────

const loggedUnknownEvents = new Set<string>();

export function logUnknownEventOnce(name: string): void {
  if (loggedUnknownEvents.has(name)) return;
  loggedUnknownEvents.add(name);
  console.warn(`Unknown event type '${name}'; skipping.`);
}

// ── Agent Events ─────────────────────────────────────────────────────────────

function projectAgentStart(state: unknown, _msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  return {
    ...current,
    agent_active: true,
    last_action_result: success("agent_start", "agent processing started"),
  };
}

function projectAgentEnd(state: unknown, msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  const data = asRecord(msg);
  const messages = data.messages;
  return {
    ...current,
    agent_active: false,
    agent_messages: Array.isArray(messages)
      ? [...(current as ExtendedFrontendState).agent_messages, ...messages]
      : (current as ExtendedFrontendState).agent_messages,
    last_action_result: success("agent_end", `agent completed with ${Array.isArray(messages) ? messages.length : 0} messages`),
  };
}

// ── Turn Events ──────────────────────────────────────────────────────────────

function projectTurnStart(state: unknown, _msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  return {
    ...current,
    turn_active: true,
    last_action_result: success("turn_start", "new turn started"),
  };
}

function projectTurnEnd(state: unknown, msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  const data = asRecord(msg);
  const message = data.message;
  const toolResults = data.toolResults;
  return {
    ...current,
    turn_active: false,
    last_turn_message: message ?? null,
    last_turn_tool_results: Array.isArray(toolResults) ? toolResults : null,
    last_action_result: success(
      "turn_end",
      `turn completed: ${message ? "with message" : "no message"}, ${Array.isArray(toolResults) ? toolResults.length : 0} tool results`,
    ),
  };
}

// ── Tool Execution Events ─────────────────────────────────────────────────────

function projectToolExecutionStart(state: unknown, msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  const data = asRecord(msg);
  const toolCallId = stringValue(data.toolCallId) ?? stringValue(data.executionId) ?? null;
  const toolName = stringValue(data.toolName) ?? stringValue(data.name) ?? "unknown";
  const args = data.args ?? data.input ?? {};
  return {
    ...current,
    tool_executions: {
      ...(current as ExtendedFrontendState).tool_executions,
      [toolCallId ?? "unknown"]: {
        id: toolCallId,
        name: toolName,
        args: args,
        status: "running",
        output: null,
        error: null,
      },
    },
    last_action_result: success("tool_execution_start", `tool ${toolName} (${toolCallId}) started`),
  };
}

function projectToolExecutionUpdate(state: unknown, msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  const data = asRecord(msg);
  const toolCallId = stringValue(data.toolCallId) ?? stringValue(data.executionId) ?? "unknown";
  const toolName = stringValue(data.toolName) ?? "unknown";
  const delta = stringValue(data.delta);
  const partialResult = data.partialResult;

  const executions = (current as ExtendedFrontendState).tool_executions;
  const existing = executions[toolCallId];

  if (existing) {
    const newOutput: ToolOutput = existing.output ? { ...existing.output } : {};
    if (delta !== null) {
      newOutput.accumulated = (newOutput.accumulated ?? "") + delta;
    }
    return {
      ...current,
      tool_executions: {
        ...executions,
        [toolCallId]: {
          ...existing,
          output: partialResult ?? newOutput,
          status: "running",
        },
      },
      last_action_result: success("tool_execution_update", `tool ${toolName} (${toolCallId}) update`),
    };
  }

  return {
    ...current,
    tool_executions: {
      ...executions,
      [toolCallId]: {
        id: toolCallId,
        name: toolName,
        args: {},
        status: "running",
        output: partialResult ?? null,
        error: null,
      },
    },
    last_action_result: success("tool_execution_update", `tool ${toolName} (${toolCallId}) update (new)`),
  };
}

function projectToolExecutionEnd(state: unknown, msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  const data = asRecord(msg);
  const toolCallId = stringValue(data.toolCallId) ?? stringValue(data.executionId) ?? "unknown";
  const toolName = stringValue(data.toolName) ?? "unknown";
  const result = data.result ?? data.output;
  const isError = booleanValue(data.isError) ?? data.error !== undefined;
  const errorMessage = stringValue(data.error);

  const executions = (current as ExtendedFrontendState).tool_executions;
  const existing = executions[toolCallId];

  return {
    ...current,
    tool_executions: {
      ...executions,
      [toolCallId]: {
        id: existing?.id ?? toolCallId,
        name: existing?.name ?? toolName,
        args: existing?.args ?? {},
        status: isError ? "error" : "completed",
        output: result ?? existing?.output ?? null,
        error: errorMessage ?? (isError ? "unknown error" : null),
      },
    },
    last_action_result: success(
      "tool_execution_end",
      `tool ${toolName} (${toolCallId}) ${isError ? "error" : "completed"}`,
    ),
  };
}

// ── Queue Events ──────────────────────────────────────────────────────────────

function projectQueueUpdate(state: unknown, msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  const data = asRecord(msg);
  const steering = Array.isArray(data.steering) ? data.steering : [];
  const followUp = Array.isArray(data.followUp) ? data.followUp : [];
  return {
    ...current,
    queue_steering: steering,
    queue_follow_up: followUp,
    last_action_result: success(
      "queue_update",
      `queue updated: ${steering.length} steering, ${followUp.length} follow-up`,
    ),
  };
}

// ── Compaction Events ─────────────────────────────────────────────────────────

function projectCompactionStart(state: unknown, msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  const data = asRecord(msg);
  const reason = stringValue(data.reason) ?? "unknown";
  return {
    ...current,
    compaction_active: true,
    compaction_reason: reason,
    last_action_result: success("compaction_start", `compaction started: ${reason}`),
  };
}

function projectCompactionEnd(state: unknown, msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  const data = asRecord(msg);
  const reason = stringValue(data.reason) ?? "unknown";
  const aborted = booleanValue(data.aborted) ?? false;
  const willRetry = booleanValue(data.willRetry) ?? false;
  const errorMessage = stringValue(data.errorMessage);

  return {
    ...current,
    compaction_active: false,
    compaction_result: data.result,
    last_action_result: success(
      "compaction_end",
      `compaction ${reason} ${aborted ? "aborted" : errorMessage ? "failed" : "completed"}` +
        (willRetry ? " (will retry)" : ""),
    ),
  };
}

// ── Auto-Retry Events ─────────────────────────────────────────────────────────

function projectAutoRetryStart(state: unknown, msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  const data = asRecord(msg);
  const attempt = numberValue(data.attempt) ?? 1;
  const maxAttempts = numberValue(data.maxAttempts) ?? 3;
  const delayMs = numberValue(data.delayMs);
  const errorMessage = stringValue(data.errorMessage);
  return {
    ...current,
    auto_retry_active: true,
    auto_retry_attempt: attempt,
    auto_retry_max_attempts: maxAttempts,
    auto_retry_delay_ms: delayMs,
    auto_retry_error: errorMessage,
    last_action_result: success(
      "auto_retry_start",
      `auto-retry ${attempt}/${maxAttempts} in ${delayMs}ms: ${errorMessage ?? "no error details"}`,
    ),
  };
}

function projectAutoRetryEnd(state: unknown, msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  const data = asRecord(msg);
  const success_ = booleanValue(data.success) ?? false;
  const attempt = numberValue(data.attempt);
  const finalError = stringValue(data.finalError);

  return {
    ...current,
    auto_retry_active: false,
    auto_retry_final_success: success_,
    auto_retry_final_error: finalError ?? null,
    last_action_result: success(
      "auto_retry_end",
      `auto-retry ${success_ ? "succeeded" : `failed: ${finalError ?? "unknown error"}`}`,
    ),
  };
}

// ── Extension Events ───────────────────────────────────────────────────────────

function projectExtensionError(state: unknown, msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  const data = asRecord(msg);
  const extensionPath = stringValue(data.extensionPath);
  const event = stringValue(data.event);
  const error = stringValue(data.error);
  return {
    ...current,
    last_extension_error: {
      extension_path: extensionPath,
      event: event,
      error: error,
    },
    last_action_result: failure("extension_error", `extension error in ${event}: ${error}`),
  };
}

// ── Utility Functions ─────────────────────────────────────────────────────────

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function booleanValue(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function success(code: string, message: string): LastActionResult {
  return { ok: true, code, message };
}

function failure(code: string, message: string): LastActionResult {
  return { ok: false, code, message };
}

// Re-export types for external use
export type { LastActionResult };
