/**
 * Pi RPC Message Event Projections
 *
 * Handles the three message lifecycle events: message_start, message_update, message_end.
 * message_update contains the largest projection with 13 sub-event types (text, thinking, toolcall, etc.).
 */

import type {
  LastActionResult,
} from "./types.ts";
import type {
  ExtendedFrontendState,
  CurrentMessage,
} from "./pi_rpc_event_types.ts";

// ── Message Events ───────────────────────────────────────────────────────────

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function success(code: string, message: string): LastActionResult {
  return { ok: true, code, message };
}

function failure(code: string, message: string): LastActionResult {
  return { ok: false, code, message };
}

export function projectMessageStart(state: unknown, msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  const data = asRecord(msg);
  const message = asRecord(data.message);
  const messageType = stringValue(message.type) ?? "unknown";
  const messageId = stringValue(message.id) ?? null;
  return {
    ...current,
    current_message: {
      id: messageId,
      type: messageType,
      content: [],
    },
    last_action_result: success("message_start", `message started: ${messageType}`),
  };
}

export function projectMessageUpdate(state: unknown, msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  const data = asRecord(msg);
  const event = asRecord(data.assistantMessageEvent);
  const eventType = stringValue(event.type);

  if (!eventType) {
    return current;
  }

  const currentMessage = (current as ExtendedFrontendState).current_message;

  switch (eventType) {
    case "start":
      return {
        ...current,
        current_message: currentMessage ?? { id: null, type: "assistant", content: [] },
        last_action_result: success("message_update", "message generation started"),
      };

    case "text_start": {
      const contentIndex = numberValue(event.contentIndex) ?? 0;
      const newContent = [...(currentMessage?.content ?? [])];
      newContent[contentIndex] = { type: "text", text: "" };
      return {
        ...current,
        current_message: currentMessage
          ? { ...currentMessage, content: newContent }
          : { id: null, type: "assistant", content: newContent },
        last_action_result: success("message_update", `text block ${contentIndex} started`),
      };
    }

    case "text_delta": {
      const delta = stringValue(event.delta) ?? "";
      const contentIndex = numberValue(event.contentIndex) ?? 0;
      const newContent = [...(currentMessage?.content ?? [])];
      const existingBlock = newContent[contentIndex];
      if (existingBlock && existingBlock.type === "text") {
        newContent[contentIndex] = { type: "text", text: existingBlock.text + delta };
      }
      return {
        ...current,
        current_message: currentMessage
          ? { ...currentMessage, content: newContent }
          : { id: null, type: "assistant", content: newContent },
        last_action_result: success("message_update", `text delta: +${delta.length} chars`),
      };
    }

    case "text_end": {
      const content = stringValue(event.content);
      const contentIndex = numberValue(event.contentIndex) ?? 0;
      const newContent = [...(currentMessage?.content ?? [])];
      if (content !== null) {
        newContent[contentIndex] = { type: "text", text: content };
      }
      return {
        ...current,
        current_message: currentMessage
          ? { ...currentMessage, content: newContent }
          : { id: null, type: "assistant", content: newContent },
        last_action_result: success("message_update", `text block ${contentIndex} ended`),
      };
    }

    case "thinking_start": {
      const contentIndex = numberValue(event.contentIndex) ?? 0;
      const newContent = [...(currentMessage?.content ?? [])];
      newContent[contentIndex] = { type: "thinking", thinking: "" };
      return {
        ...current,
        current_message: currentMessage
          ? { ...currentMessage, content: newContent }
          : { id: null, type: "assistant", content: newContent },
        last_action_result: success("message_update", `thinking block ${contentIndex} started`),
      };
    }

    case "thinking_delta": {
      const delta = stringValue(event.delta) ?? "";
      const contentIndex = numberValue(event.contentIndex) ?? 0;
      const newContent = [...(currentMessage?.content ?? [])];
      const existingBlock = newContent[contentIndex];
      if (existingBlock && existingBlock.type === "thinking") {
        newContent[contentIndex] = { type: "thinking", thinking: existingBlock.thinking + delta };
      }
      return {
        ...current,
        current_message: currentMessage
          ? { ...currentMessage, content: newContent }
          : { id: null, type: "assistant", content: newContent },
        last_action_result: success("message_update", `thinking delta: +${delta.length} chars`),
      };
    }

    case "thinking_end": {
      const contentIndex = numberValue(event.contentIndex) ?? 0;
      return {
        ...current,
        current_message: currentMessage ? { ...currentMessage } : { id: null, type: "assistant", content: [] },
        last_action_result: success("message_update", `thinking block ${contentIndex} ended`),
      };
    }

    case "toolcall_start": {
      const partial = asRecord(event.partial);
      const name = stringValue(partial.name) ?? "unknown";
      const toolCallId = stringValue(partial.id) ?? null;
      return {
        ...current,
        current_tool_call: { id: toolCallId, name, arguments: "" },
        last_action_result: success("message_update", `toolcall started: ${name}`),
      };
    }

    case "toolcall_delta": {
      const delta = stringValue(event.delta) ?? "";
      const currentToolCall = (current as ExtendedFrontendState).current_tool_call;
      return {
        ...current,
        current_tool_call: currentToolCall
          ? { ...currentToolCall, arguments: currentToolCall.arguments + delta }
          : { id: null, name: "unknown", arguments: delta },
        last_action_result: success("message_update", `toolcall delta: +${delta.length} chars`),
      };
    }

    case "toolcall_end": {
      const toolCall = asRecord(event.toolCall);
      const name = stringValue(toolCall.name) ?? "unknown";
      const toolCallId = stringValue(toolCall.id) ?? null;
      const args = stringValue(toolCall.arguments);
      return {
        ...current,
        current_tool_call: null,
        last_tool_call: { id: toolCallId, name, arguments: args ?? "" },
        last_action_result: success("message_update", `toolcall ended: ${name}`),
      };
    }

    case "done": {
      const reason = stringValue(event.reason) ?? "unknown";
      return {
        ...current,
        last_action_result: success("message_update", `message complete: ${reason}`),
      };
    }

    case "error": {
      const reason = stringValue(event.reason) ?? "unknown";
      return {
        ...current,
        last_action_result: failure("message_error", `message error: ${reason}`),
      };
    }

    default:
      return current;
  }
}

export function projectMessageEnd(state: unknown, msg: unknown): unknown {
  const current = state as ExtendedFrontendState;
  const data = asRecord(msg);
  const message = asRecord(data.message);
  const messageType = stringValue(message.type) ?? "unknown";
  const messageId = stringValue(message.id) ?? null;
  return {
    ...current,
    completed_messages: [
      ...(current as ExtendedFrontendState).completed_messages,
      { id: messageId, type: messageType, content: (current as ExtendedFrontendState).current_message?.content ?? [] },
    ],
    current_message: null,
    last_action_result: success("message_end", `message completed: ${messageType}`),
  };
}
