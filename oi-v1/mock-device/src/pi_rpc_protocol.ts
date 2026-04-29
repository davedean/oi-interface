/**
 * Pi RPC Protocol — re-exports.
 *
 * This file is a thin re-export layer for backwards compatibility.
 * Actual implementations live in:
 *   - pi_rpc_ui_handlers.ts    (UI_METHOD_HANDLERS, dialog/fire-and-forget handlers)
 *   - pi_rpc_state_mapper.ts   (state mapping, prompt mapping, response parsers)
 */

export {
  UI_METHOD_HANDLERS,
  type ExtensionUiResponse,
  type ExtensionUiValueResponse,
  type ExtensionUiConfirmResponse,
  type ExtensionUiCancelledResponse,
} from "./pi_rpc_ui_handlers.ts";

export {
  mapGetStateToSnapshot,
  mapExtensionUiRequest,
  rpcInboundToEffect,
  applyRpcCommandStatusUpdate,
  mapSetModelResponse,
  mapCycleModelResponse,
  mapSetThinkingLevelResponse,
  mapCycleThinkingLevelResponse,
  mapSetSteeringModeResponse,
  mapSetFollowUpModeResponse,
  mapSetAutoCompactionResponse,
  mapSetAutoRetryResponse,
  mapSetSessionNameResponse,
  type ExtensionUiPrompt,
  type RpcInboundEffect,
  type ModelInfo,
  type CycleModelResponse,
  type CycleThinkingLevelResponse,
} from "./pi_rpc_state_mapper.ts";
