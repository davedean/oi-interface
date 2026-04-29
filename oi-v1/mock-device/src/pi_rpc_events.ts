/**
 * Pi RPC Events — re-exports.
 *
 * This file is a thin re-export layer for backwards compatibility.
 * Actual implementations live in:
 *   - pi_rpc_event_projections.ts  (all 16 project* functions, EVENT_PROJECTIONS)
 *   - pi_rpc_event_types.ts        (ExtendedFrontendState and related types)
 */

export {
  EVENT_PROJECTIONS,
  logUnknownEventOnce,
  type LastActionResult,
} from "./pi_rpc_event_projections.ts";

export {
  projectMessageStart,
  projectMessageUpdate,
  projectMessageEnd,
} from "./pi_rpc_message_projections.ts";

export {
  type ExtendedFrontendState,
  type CurrentMessage,
  type CompletedMessage,
  type MessageContent,
  type CurrentToolCall,
  type LastToolCall,
  type ToolOutput,
  type ToolExecution,
  type ExtensionError,
  type FrontendState,
} from "./pi_rpc_event_types.ts";
