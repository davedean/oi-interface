import type { FrontendState, PromptSummary, ReducerFrame, SnapshotData } from "./types.ts";

// ── Extension UI Response types ────────────────────────────────────────────────

/** Response shape for dialog methods that return a value (select, input, editor). */
export interface ExtensionUiValueResponse {
  type: "extension_ui_response";
  id: string;
  value: string;
}

/** Response shape for confirm dialog method. */
export interface ExtensionUiConfirmResponse {
  type: "extension_ui_response";
  id: string;
  confirmed: boolean;
}

/** Response shape for dialog cancellation. */
export interface ExtensionUiCancelledResponse {
  type: "extension_ui_response";
  id: string;
  cancelled: true;
}

/** Union of all possible extension UI response shapes. */
export type ExtensionUiResponse = ExtensionUiValueResponse | ExtensionUiConfirmResponse | ExtensionUiCancelledResponse;

// ── Extension UI method handlers ─────────────────────────────────────────────

/**
 * Extract the request id from an extension_ui_request message.
 * Supports both `id` and legacy field names.
 */
function extractRequestId(request: Record<string, unknown>): string {
  return String(request.id ?? request.request_id ?? request.prompt_id ?? "");
}

/**
 * Surface/log a fire-and-forget request for observability.
 * Returns a summary of what was received.
 */
function surfaceFireAndForget(request: Record<string, unknown>): { method: string; surfaced: boolean } {
  const method = String(request.method ?? "unknown");
  // In a real implementation, this would update UI state, log, etc.
  // For the mock device, we just return the surface info.
  console.debug(`[extension_ui] fire-and-forget: ${method}`, request);
  return { method, surfaced: true };
}

// ── Dialog method handlers ────────────────────────────────────────────────────

/**
 * Handler for `select` method.
 * Builds a value response (user selection) or cancelled response.
 * The actual user interaction happens via the prompt system;
 * this handler builds the response shape for the transport layer.
 */
function handleSelect(request: Record<string, unknown>): ExtensionUiResponse | null {
  const id = extractRequestId(request);
  if (!id) return null;

  // For mock: simulate a default selection or cancellation
  // The real flow: prompt user → get choice → send response
  // Here we return the response shape; caller sends it
  const options = Array.isArray(request.options) ? request.options : [];
  const defaultValue = options.length > 0 ? String(options[0]) : "";

  return {
    type: "extension_ui_response",
    id,
    value: defaultValue,
  };
}

/**
 * Handler for `confirm` method.
 * Builds a confirm response (true/false) or cancelled response.
 */
function handleConfirm(request: Record<string, unknown>): ExtensionUiResponse | null {
  const id = extractRequestId(request);
  if (!id) return null;

  // For mock: default to false (user declined)
  // Real flow: prompt user → get choice → send response
  return {
    type: "extension_ui_response",
    id,
    confirmed: false,
  };
}

/**
 * Handler for `input` method.
 * Builds a value response (user input) or cancelled response.
 */
function handleInput(request: Record<string, unknown>): ExtensionUiResponse | null {
  const id = extractRequestId(request);
  if (!id) return null;

  // For mock: return empty string
  // Real flow: prompt user → get input → send response
  return {
    type: "extension_ui_response",
    id,
    value: "",
  };
}

/**
 * Handler for `editor` method.
 * Builds a value response (editor content) or cancelled response.
 */
function handleEditor(request: Record<string, unknown>): ExtensionUiResponse | null {
  const id = extractRequestId(request);
  if (!id) return null;

  // For mock: return prefilled content or empty string
  // Real flow: prompt user → get content → send response
  const prefilled = String(request.prefill ?? "");
  return {
    type: "extension_ui_response",
    id,
    value: prefilled,
  };
}

// ── Fire-and-forget method handlers ─────────────────────────────────────────

/**
 * Handler for `notify` method.
 * Displays a notification. No response expected.
 */
function handleNotify(request: Record<string, unknown>): null {
  surfaceFireAndForget(request);
  return null;
}

/**
 * Handler for `setStatus` method.
 * Sets or clears a status entry in the footer/status bar. No response expected.
 */
function handleSetStatus(request: Record<string, unknown>): null {
  surfaceFireAndForget(request);
  return null;
}

/**
 * Handler for `setWidget` method.
 * Sets or clears a widget. No response expected.
 */
function handleSetWidget(request: Record<string, unknown>): null {
  surfaceFireAndForget(request);
  return null;
}

/**
 * Handler for `setTitle` method.
 * Sets the terminal window/tab title. No response expected.
 */
function handleSetTitle(request: Record<string, unknown>): null {
  surfaceFireAndForget(request);
  return null;
}

/**
 * Handler for `set_editor_text` method.
 * Sets the text in the input editor. No response expected.
 */
function handleSetEditorText(request: Record<string, unknown>): null {
  surfaceFireAndForget(request);
  return null;
}

// ── Extension UI method dispatch table ───────────────────────────────────────

/**
 * Extension UI method dispatch table.
 *
 * - Dialog methods (select, confirm, input, editor): return a response object
 *   that should be sent back to the Pi server via the transport layer.
 * - Fire-and-forget methods (notify, setStatus, setWidget, setTitle, set_editor_text):
 *   surface/log the request and return null (no response expected).
 *
 * Casing is exact per spec:
 *   - camelCase: setStatus, setWidget, setTitle
 *   - snake_case: set_editor_text
 */
export const UI_METHOD_HANDLERS: Record<string, (request: Record<string, unknown>) => ExtensionUiResponse | null> = {
  select: handleSelect,
  confirm: handleConfirm,
  input: handleInput,
  editor: handleEditor,
  notify: handleNotify,
  setStatus: handleSetStatus,
  setWidget: handleSetWidget,
  setTitle: handleSetTitle,
  set_editor_text: handleSetEditorText,
};
