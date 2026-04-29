/**
 * Pi RPC Event Type Definitions
 *
 * Contains extended state interfaces and type definitions for event payloads
 * and state shape used by the Pi RPC event projections.
 */

import type { FrontendState, LastActionResult } from "./types.ts";

// ── Extended Frontend State ────────────────────────────────────────────────────

/** Extended state fields added by Pi RPC events */
export interface ExtendedFrontendState extends FrontendState {
  agent_active: boolean;
  agent_messages: unknown[];
  turn_active: boolean;
  last_turn_message: unknown | null;
  last_turn_tool_results: unknown[] | null;
  current_message: CurrentMessage | null;
  completed_messages: CompletedMessage[];
  current_tool_call: CurrentToolCall | null;
  last_tool_call: LastToolCall | null;
  tool_executions: Record<string, ToolExecution>;
  queue_steering: string[];
  queue_follow_up: string[];
  compaction_active: boolean;
  compaction_reason: string | null;
  compaction_result: unknown | null;
  auto_retry_active: boolean;
  auto_retry_attempt: number | null;
  auto_retry_max_attempts: number | null;
  auto_retry_delay_ms: number | null;
  auto_retry_error: string | null;
  auto_retry_final_success: boolean | null;
  auto_retry_final_error: string | null;
  last_extension_error: ExtensionError | null;
}

export interface CurrentMessage {
  id: string | null;
  type: string;
  content: MessageContent[];
}

export interface CompletedMessage {
  id: string | null;
  type: string;
  content: MessageContent[];
}

export interface MessageContent {
  type: "text" | "thinking";
  text?: string;
  thinking?: string;
}

export interface CurrentToolCall {
  id: string | null;
  name: string;
  arguments: string;
}

export interface LastToolCall {
  id: string | null;
  name: string;
  arguments: string;
}

export interface ToolOutput {
  content?: unknown[];
  details?: unknown;
  accumulated?: string;
}

export interface ToolExecution {
  id: string | null;
  name: string;
  args: unknown;
  status: "running" | "completed" | "error";
  output: ToolOutput | null;
  error: string | null;
}

export interface ExtensionError {
  extension_path: string | null;
  event: string | null;
  error: string | null;
}

// Re-export core types for external use
export type { FrontendState, LastActionResult };
