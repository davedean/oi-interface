import type { FrontendState, PromptSummary, ReducerFrame, SnapshotData } from "./types.ts";

// ── get_state → SnapshotData mapping ─────────────────────────────────────────

/**
 * Map a Pi RPC `get_state` response into a reducer-compatible SnapshotData.
 *
 * Supports both the real envelope format:
 *   {type:"response", command:"get_state", success:true, data:{...}}
 * and a tolerant fallback that treats the whole object as data
 * (for legacy/bare responses).
 */
export function mapGetStateToSnapshot(response: Record<string, unknown>): SnapshotData {
  // Unwrap envelope: {type:"response", command:"get_state", success:true, data:{...}}
  let data = response;
  if (
    response.type === "response" &&
    (response.command === "get_state" || response.command === "get_state_response") &&
    typeof response.data === "object" && response.data !== null
  ) {
    data = response.data as Record<string, unknown>;
  }

  const sessionId = String(data.session_id ?? data.id ?? "");
  const sessionName = String(data.name ?? data.session_name ?? sessionId);
  const sessionStatus = String(data.status ?? data.session_status ?? "unknown");
  const activeSessionId = sessionId || null;

  // Build session list from top-level or nested sessions array
  let sessionList: SnapshotData["sessions"] = {
    active_session_id: activeSessionId,
    list: sessionId
      ? [{
          session_id: sessionId,
          name: sessionName,
          status: sessionStatus,
          pending_count: typeof data.pending_count === "number" ? data.pending_count : 0,
          stale: data.stale === true,
          last_seen_age_s: typeof data.last_seen_age_s === "number" ? data.last_seen_age_s : null,
        }]
      : [],
  };

  // If data has a sessions array, prefer it
  if (Array.isArray(data.sessions)) {
    sessionList = {
      active_session_id: (typeof data.active_session_id === "string" ? data.active_session_id : activeSessionId) ?? null,
      list: (data.sessions as Record<string, unknown>[]).map(normaliseRpcSession),
    };
  }

  // Pending prompts from top-level or nested
  // In single-session mode (get_state), assign the active session if missing
  const prompts: PromptSummary[] = [];
  if (data.pending_prompt && typeof data.pending_prompt === "object") {
    const p = normaliseRpcPrompt(data.pending_prompt as Record<string, unknown>);
    if (p) prompts.push({ ...p, session_id: p.session_id ?? activeSessionId });
  }
  if (Array.isArray(data.prompts)) {
    for (const p of data.prompts as Record<string, unknown>[]) {
      const norm = normaliseRpcPrompt(p);
      if (norm) prompts.push({ ...norm, session_id: norm.session_id ?? activeSessionId });
    }
  }

  // Queue health
  const qh = data.queue_health as Record<string, unknown> | undefined;

  // Queued commands
  const commands = Array.isArray(data.queued_commands)
    ? (data.queued_commands as Record<string, unknown>[]).map(normaliseRpcCommand).filter((c): c is NonNullable<typeof c> => c !== null)
    : [];

  return {
    view: (typeof data.view === "string" ? data.view : undefined) as SnapshotData["view"],
    sessions: sessionList,
    prompts,
    queue_health: qh
      ? {
          oldest_pending_prompt_age_s: typeof qh.oldest_pending_prompt_age_s === "number" ? qh.oldest_pending_prompt_age_s : null,
          oldest_queued_command_age_s: typeof qh.oldest_queued_command_age_s === "number" ? qh.oldest_queued_command_age_s : null,
        }
      : undefined,
    queued_commands: commands,
    device_hint: data.device_hint as SnapshotData["device_hint"],
    last_action_result: data.last_action_result as SnapshotData["last_action_result"],
  };
}

// ── extension_ui_request → PromptSummary mapping ─────────────────────────────

export interface ExtensionUiPrompt {
  prompt_id: string | null;
  session_id: string | null;
  title: string | null;
  body: string | null;
  options: PromptSummary["options"];
  ui_type: string | null;
  extension_prompt_id: string | null;
}

/**
 * Map a Pi RPC `extension_ui_request` message to a PromptSummary for the reducer.
 *
 * Supports the real protocol shape:
 *   { type: "extension_ui_request", id, method, title, message, options, session_id, ... }
 * Also tolerates legacy shapes with ui_type, prompt_id, body, extension_prompt_id.
 */
export function mapExtensionUiRequest(msg: Record<string, unknown>): ExtensionUiPrompt {
  const promptId = str(msg.prompt_id ?? msg.id) ?? `ext-${Date.now()}`;
  const rawOptions = Array.isArray(msg.options) ? msg.options : [];
  const options = rawOptions
    .map((o: unknown) => {
      if (typeof o === "object" && o !== null) {
        const obj = o as Record<string, unknown>;
        return { label: str(obj.label) ?? str(obj.value) ?? "", value: str(obj.value) ?? str(obj.label) ?? "" };
      }
      return null;
    })
    .filter((o): o is { label: string; value: string } => o !== null);

  return {
    prompt_id: promptId,
    session_id: str(msg.session_id) ?? null,
    title: str(msg.title) ?? null,
    body: str(msg.body ?? msg.message) ?? null,
    options,
    ui_type: str(msg.ui_type ?? msg.method) ?? null,
    extension_prompt_id: str(msg.extension_prompt_id ?? msg.id) ?? null,
  };
}

// ── inbound RPC message dispatcher helpers ──────────────────────────────────

export type RpcInboundEffect =
  | {
      kind: "prompt";
      frame: ReducerFrame;
      prompt_id: string;
      extension_prompt_id: string | null;
    }
  | { kind: "snapshot"; frame: ReducerFrame }
  | { kind: "command_status"; command_id: string; status: string }
  | { kind: "error"; message: string }
  | { kind: "ignore" };

const UI_REQUEST_MESSAGE_TYPES = new Set(["extension_ui_request", "select", "confirm", "input", "prompt"]);
const SNAPSHOT_MESSAGE_TYPES = new Set(["response", "state", "get_state_response", "snapshot"]);
const COMMAND_STATUS_MESSAGE_TYPES = new Set(["command_acked", "command_result"]);

/** Convert an inbound Pi RPC message into a reducer-oriented effect. */
export function rpcInboundToEffect(msg: Record<string, unknown>): RpcInboundEffect {
  const type = str(msg.type);
  if (!type) return { kind: "ignore" };

  if (UI_REQUEST_MESSAGE_TYPES.has(type)) {
    const ext = mapExtensionUiRequest(msg);
    const promptSummary: PromptSummary = {
      prompt_id: ext.prompt_id ?? `ext-${Date.now()}`,
      session_id: ext.session_id,
      title: ext.title,
      body: ext.body,
      options: ext.options,
      status: "pending",
    };
    return {
      kind: "prompt",
      prompt_id: promptSummary.prompt_id,
      extension_prompt_id: ext.extension_prompt_id,
      frame: {
        type: "event",
        name: "prompt.pending",
        data: promptSummary as unknown as Record<string, unknown>,
      },
    };
  }

  if (SNAPSHOT_MESSAGE_TYPES.has(type)) {
    return {
      kind: "snapshot",
      frame: { type: "snapshot", data: mapGetStateToSnapshot(msg) },
    };
  }

  if (COMMAND_STATUS_MESSAGE_TYPES.has(type)) {
    const commandId = String(msg.command_id ?? msg.id ?? "");
    if (commandId.length === 0) return { kind: "ignore" };
    return { kind: "command_status", command_id: commandId, status: String(msg.status ?? "acked") };
  }

  if (type === "error") {
    return { kind: "error", message: String(msg.message ?? msg.error ?? "unknown") };
  }

  return { kind: "ignore" };
}

/** Apply a command status effect. Kept pure so main only handles rendering/I/O. */
export function applyRpcCommandStatusUpdate(
  state: FrontendState,
  update: { command_id: string; status: string },
): FrontendState {
  return {
    ...state,
    queued_commands: state.queued_commands.map((c) =>
      c.command_id === update.command_id ? { ...c, status: update.status } : c,
    ),
  };
}

// ── Step 3b: Mode/setting command response parsers ───────────────────────────

export interface ModelInfo {
  id: string;
  name: string;
  api: string;
  provider: string;
  baseUrl?: string;
  reasoning?: boolean;
  input?: string[];
  contextWindow?: number;
  maxTokens?: number;
  cost?: {
    input: number;
    output: number;
    cacheRead: number;
    cacheWrite: number;
  };
}

export interface CycleModelResponse {
  model: ModelInfo | null;
  thinkingLevel: string | null;
  isScoped: boolean;
}

export interface CycleThinkingLevelResponse {
  level: string | null;
}

/**
 * Map a Pi RPC `set_model` response. Returns the Model object on success.
 */
export function mapSetModelResponse(response: Record<string, unknown>): { success: boolean; model?: ModelInfo; error?: string } {
  const success = response.success === true;
  if (!success) {
    return { success: false, error: str(response.error) ?? "unknown error" };
  }
  let data = response;
  if (
    response.type === "response" &&
    response.command === "set_model" &&
    typeof response.data === "object" && response.data !== null
  ) {
    data = response.data as Record<string, unknown>;
  }
  const model = normaliseModel(data);
  return { success: true, model: model ?? undefined };
}

/**
 * Map a Pi RPC `cycle_model` response.
 * Returns null data if only one model available.
 */
export function mapCycleModelResponse(response: Record<string, unknown>): { success: boolean; data?: CycleModelResponse | null; error?: string } {
  const success = response.success === true;
  if (!success) {
    return { success: false, error: str(response.error) ?? "unknown error" };
  }
  let data = response;
  if (
    response.type === "response" &&
    response.command === "cycle_model" &&
    typeof response.data === "object" && response.data !== null
  ) {
    data = response.data as Record<string, unknown>;
  }
  if (!data || Object.keys(data).length === 0) {
    return { success: true, data: null };
  }
  const model = normaliseModel(data.model as Record<string, unknown> | undefined);
  return {
    success: true,
    data: {
      model: model ?? null,
      thinkingLevel: str(data.thinkingLevel ?? data.thinking_level) ?? null,
      isScoped: data.isScoped === true || data.is_scoped === true,
    },
  };
}

/**
 * Map a Pi RPC `set_thinking_level` response.
 */
export function mapSetThinkingLevelResponse(response: Record<string, unknown>): { success: boolean; error?: string } {
  const success = response.success === true;
  if (!success) {
    return { success: false, error: str(response.error) ?? "unknown error" };
  }
  return { success: true };
}

/**
 * Map a Pi RPC `cycle_thinking_level` response.
 * Returns null data if model doesn't support thinking.
 */
export function mapCycleThinkingLevelResponse(response: Record<string, unknown>): { success: boolean; data?: CycleThinkingLevelResponse | null; error?: string } {
  const success = response.success === true;
  if (!success) {
    return { success: false, error: str(response.error) ?? "unknown error" };
  }
  let data = response;
  if (
    response.type === "response" &&
    response.command === "cycle_thinking_level" &&
    typeof response.data === "object" && response.data !== null
  ) {
    data = response.data as Record<string, unknown>;
  }
  if (!data || Object.keys(data).length === 0) {
    return { success: true, data: null };
  }
  return {
    success: true,
    data: {
      level: str(data.level) ?? null,
    },
  };
}

/**
 * Map a Pi RPC `set_steering_mode` response.
 */
export function mapSetSteeringModeResponse(response: Record<string, unknown>): { success: boolean; error?: string } {
  const success = response.success === true;
  if (!success) {
    return { success: false, error: str(response.error) ?? "unknown error" };
  }
  return { success: true };
}

/**
 * Map a Pi RPC `set_follow_up_mode` response.
 */
export function mapSetFollowUpModeResponse(response: Record<string, unknown>): { success: boolean; error?: string } {
  const success = response.success === true;
  if (!success) {
    return { success: false, error: str(response.error) ?? "unknown error" };
  }
  return { success: true };
}

/**
 * Map a Pi RPC `set_auto_compaction` response.
 */
export function mapSetAutoCompactionResponse(response: Record<string, unknown>): { success: boolean; error?: string } {
  const success = response.success === true;
  if (!success) {
    return { success: false, error: str(response.error) ?? "unknown error" };
  }
  return { success: true };
}

/**
 * Map a Pi RPC `set_auto_retry` response.
 */
export function mapSetAutoRetryResponse(response: Record<string, unknown>): { success: boolean; error?: string } {
  const success = response.success === true;
  if (!success) {
    return { success: false, error: str(response.error) ?? "unknown error" };
  }
  return { success: true };
}

/**
 * Map a Pi RPC `set_session_name` response.
 */
export function mapSetSessionNameResponse(response: Record<string, unknown>): { success: boolean; error?: string } {
  const success = response.success === true;
  if (!success) {
    return { success: false, error: str(response.error) ?? "unknown error" };
  }
  return { success: true };
}

// ── Internal helpers ─────────────────────────────────────────────────────────

function str(val: unknown): string | null {
  return typeof val === "string" && val.length > 0 ? val : null;
}

function num(val: unknown): number | null {
  return typeof val === "number" && !Number.isNaN(val) ? val : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function normaliseModel(m: Record<string, unknown> | undefined): ModelInfo | null {
  if (!m || typeof m !== "object") return null;
  const id = str(m.id);
  if (!id) return null;
  const costObj = isRecord(m.cost) ? (m.cost as Record<string, unknown>) : undefined;
  return {
    id,
    name: str(m.name) ?? id,
    api: str(m.api) ?? "unknown",
    provider: str(m.provider) ?? "unknown",
    baseUrl: str(m.baseUrl ?? m.base_url) ?? undefined,
    reasoning: m.reasoning === true,
    input: Array.isArray(m.input) ? m.input as string[] : undefined,
    contextWindow: num(m.contextWindow ?? m.context_window) ?? undefined,
    maxTokens: num(m.maxTokens ?? m.max_tokens) ?? undefined,
    cost: costObj ? {
      input: num(costObj.input) ?? 0,
      output: num(costObj.output) ?? 0,
      cacheRead: num(costObj.cacheRead ?? costObj.cache_read) ?? 0,
      cacheWrite: num(costObj.cacheWrite ?? costObj.cache_write) ?? 0,
    } : undefined,
  };
}

function normaliseRpcSession(s: Record<string, unknown>): import("./types.ts").SessionSummary {
  return {
    session_id: String(s.session_id ?? s.id ?? ""),
    name: String(s.name ?? s.session_name ?? s.session_id ?? ""),
    status: String(s.status ?? s.session_status ?? "unknown"),
    pending_count: typeof s.pending_count === "number" ? s.pending_count : 0,
    stale: s.stale === true,
    last_seen_age_s: typeof s.last_seen_age_s === "number" ? s.last_seen_age_s : null,
  };
}

function normaliseRpcPrompt(p: Record<string, unknown>): PromptSummary | null {
  const promptId = String(p.prompt_id ?? p.id ?? "");
  if (!promptId) return null;
  const rawOpts = Array.isArray(p.options) ? p.options : [];
  const options = rawOpts
    .map((o: unknown) => {
      if (typeof o === "object" && o !== null) {
        const obj = o as Record<string, unknown>;
        return { label: String(obj.label ?? obj.value ?? ""), value: String(obj.value ?? obj.label ?? "") };
      }
      return null;
    })
    .filter((o): o is { label: string; value: string } => o !== null);

  return {
    prompt_id: promptId,
    session_id: typeof p.session_id === "string" ? p.session_id : null,
    title: typeof p.title === "string" ? p.title : null,
    body: typeof p.body === "string" ? p.body : null,
    options,
    status: String(p.status ?? "pending"),
  };
}

function normaliseRpcCommand(c: Record<string, unknown>) {
  const commandId = String(c.command_id ?? c.id ?? "");
  const sessionId = String(c.session_id ?? "");
  const verb = String(c.verb ?? "");
  if (!commandId || !sessionId || !verb) return null;
  return {
    command_id: commandId,
    session_id: sessionId,
    verb,
    status: String(c.status ?? "queued"),
    request_id: typeof c.request_id === "string" ? c.request_id : null,
  };
}
