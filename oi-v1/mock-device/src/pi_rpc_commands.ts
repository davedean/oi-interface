// ── action → rpc command mapping ─────────────────────────────────────────────

/** Supported Pi RPC command verbs (subset of command.queue verbs). */
export const RPC_SUPPORTED_VERBS = new Set(["status", "abort", "follow_up", "steer", "prompt"]);
/** Verbs that stay local (no RPC mapping, use reducer directly). */
export const LOCAL_ONLY_VERBS = new Set(["speak"]);

/** Verb-to-RPC-type mapping for outbound commands. */
const VERB_TO_TYPE: Record<string, string> = {
  status: "get_state",
  abort: "abort",
  follow_up: "follow_up",
  steer: "steer",
  prompt: "prompt",
};

/** Verbs that carry a message payload. */
const MESSAGE_COMMANDS = new Set(["follow_up", "steer", "prompt"]);

/** Commands that carry no payload (read-only). */
const NO_PAYLOAD_COMMANDS = new Set([
  "get_messages",
  "get_available_models",
  "get_session_stats",
  "get_fork_messages",
  "get_last_assistant_text",
  "get_commands",
]);

/** Existing outbound Pi RPC command builders. Later parity steps add more. */
export const COMMAND_BUILDERS: Record<string, (...args: unknown[]) => object> = {
  // Step 3a — Read-only commands (7)
  get_state: (args?: unknown) => buildSessionCommand("get_state", args),
  get_messages: (args?: unknown) => buildNoPayloadCommand("get_messages", args),
  get_available_models: (args?: unknown) => buildNoPayloadCommand("get_available_models", args),
  get_session_stats: (args?: unknown) => buildNoPayloadCommand("get_session_stats", args),
  get_fork_messages: (args?: unknown) => buildNoPayloadCommand("get_fork_messages", args),
  get_last_assistant_text: (args?: unknown) => buildNoPayloadCommand("get_last_assistant_text", args),
  get_commands: (args?: unknown) => buildNoPayloadCommand("get_commands", args),
  // Step 3b — Mode/setting commands (9)
  set_model: buildSetModel,
  cycle_model: buildCycleModel,
  set_thinking_level: buildSetThinkingLevel,
  cycle_thinking_level: buildCycleThinkingLevel,
  set_steering_mode: buildSetSteeringMode,
  set_follow_up_mode: buildSetFollowUpMode,
  set_auto_compaction: buildSetAutoCompaction,
  set_auto_retry: buildSetAutoRetry,
  set_session_name: buildSetSessionName,
  // Step 3c — Lifecycle/interactive
  abort: (args?: unknown) => buildSessionCommand("abort", args),
  follow_up: (args?: unknown) => buildMessageCommand("follow_up", args),
  steer: (args?: unknown) => buildSteerCommand("steer", args),
  prompt: (args?: unknown) => buildPromptCommand("prompt", args),
  new_session: (args?: unknown) => buildNewSessionCommand("new_session", args),
  switch_session: (args?: unknown) => buildSwitchSessionCommand("switch_session", args),
  abort_retry: (args?: unknown) => buildSessionCommand("abort_retry", args),
  abort_bash: (args?: unknown) => buildSessionCommand("abort_bash", args),
  // Step 3d — Heavy/destructive
  bash: buildBashCommand,
  compact: buildCompactCommand,
  fork: buildForkCommand,
  clone: buildCloneCommand,
  export_html: buildExportHtmlCommand,
};

/** Dispatch to a command builder by Pi RPC command key. */
export function buildRpcCommand(key: string, args: unknown): object {
  const builder = COMMAND_BUILDERS[key];
  if (!builder) {
    throw new Error(`unsupported Pi RPC command: ${key}`);
  }
  return builder(args);
}

/**
 * Map a `command.queue` action to an RPC command payload using the real protocol.
 * Outbound commands use {type, ...} with verb-to-type mapping:
 *   status → {type:"get_state"}, abort → {type:"abort"},
 *   follow_up → {type:"follow_up", message}, steer → {type:"steer", message},
 *   prompt → {type:"prompt", message}.
 * Returns null if the verb is local-only (not routable to RPC).
 */
export function mapActionToRpcCommand(
  actionData: Record<string, unknown>,
  activeSessionId: string | null,
): { type: string; [key: string]: unknown } | null {
  const verb = str(actionData.verb);
  if (!verb) return null;

  // Local-only verbs: no RPC command
  if (LOCAL_ONLY_VERBS.has(verb)) return null;

  // Unknown verb: don't send to RPC
  if (!RPC_SUPPORTED_VERBS.has(verb)) return null;

  const rpcType = VERB_TO_TYPE[verb] ?? verb;
  return buildRpcCommand(rpcType, {
    ...actionData,
    session_id: str(actionData.session_id) ?? activeSessionId,
  }) as { type: string; [key: string]: unknown };
}

/**
 * Map a `prompt.answer` action to an `extension_ui_response` RPC command.
 * Uses the real protocol shape: {type:"extension_ui_response", id, value}.
 * Returns null if no matching request-id is available (e.g. prompt was local).
 */
export function mapPromptAnswerToRpcCommand(
  actionData: Record<string, unknown>,
  pendingExtensionIds: Map<string, string>,
): { type: string; id: string; value: string } | null {
  const promptId = str(actionData.prompt_id);
  const value = str(actionData.value);
  if (!promptId || value === null) return null;

  const id = pendingExtensionIds.get(promptId);
  if (!id) return null;

  return {
    type: "extension_ui_response",
    id,
    value,
  };
}

function buildSessionCommand(commandType: string, args: unknown): { type: string; [key: string]: unknown } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; [key: string]: unknown } = {
    type: commandType,
    session_id: str(data.session_id),
  };

  if (data.request_id) {
    result.request_id = str(data.request_id);
  }

  return result;
}

/**
 * Build a no-payload command (read-only commands with no arguments).
 * Only includes the type field, optionally with session_id if provided.
 */
function buildNoPayloadCommand(commandType: string, args: unknown): { type: string; [key: string]: unknown } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; [key: string]: unknown } = {
    type: commandType,
  };

  // Include session_id only if explicitly provided
  const sessionId = str(data.session_id);
  if (sessionId) {
    result.session_id = sessionId;
  }

  return result;
}

function buildMessageCommand(commandType: string, args: unknown): { type: string; [key: string]: unknown } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; [key: string]: unknown } = {
    type: commandType,
    session_id: str(data.session_id),
  };

  const message = str(data.message);
  if (message) result.message = message;

  if (data.request_id) {
    result.request_id = str(data.request_id);
  }

  return result;
}

function buildSteerCommand(commandType: string, args: unknown): { type: string; [key: string]: unknown } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; [key: string]: unknown } = {
    type: commandType,
    session_id: str(data.session_id),
  };

  const message = str(data.message);
  if (message) {
    if (message.startsWith("/")) {
      throw new Error("steer does not support extension commands; use prompt instead");
    }
    result.message = message;
  }

  if (data.request_id) {
    result.request_id = str(data.request_id);
  }

  return result;
}

function buildPromptCommand(commandType: string, args: unknown): { type: string; [key: string]: unknown } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; [key: string]: unknown } = {
    type: commandType,
    session_id: str(data.session_id),
  };

  const message = str(data.message);
  if (message) result.message = message;

  const streamingBehavior = str(data.streamingBehavior);
  if (streamingBehavior) {
    result.streamingBehavior = streamingBehavior;
  }

  if (Array.isArray(data.images)) {
    result.images = data.images;
  }

  if (data.request_id) {
    result.request_id = str(data.request_id);
  }

  return result;
}

function buildNewSessionCommand(commandType: string, args: unknown): { type: string; [key: string]: unknown } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; [key: string]: unknown } = {
    type: commandType,
  };

  const parentSession = str(data.parentSession);
  if (parentSession) {
    result.parentSession = parentSession;
  }

  return result;
}

function buildSwitchSessionCommand(commandType: string, args: unknown): { type: string; [key: string]: unknown } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; [key: string]: unknown } = {
    type: commandType,
  };

  const sessionPath = str(data.sessionPath);
  if (sessionPath) {
    result.sessionPath = sessionPath;
  }

  return result;
}

// ── Step 3b: Mode/setting command builders ────────────────────────────────────

/**
 * Build a set_model command. Args: {provider, modelId}.
 * Spec: {type:"set_model", provider, modelId}
 */
function buildSetModel(args?: unknown): { type: string; provider?: string; modelId?: string } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; provider?: string; modelId?: string } = {
    type: "set_model",
  };
  const provider = str(data.provider);
  const modelId = str(data.modelId);
  if (provider) result.provider = provider;
  if (modelId) result.modelId = modelId;
  return result;
}

/**
 * Build a cycle_model command. No args.
 * Spec: {type:"cycle_model"}
 */
function buildCycleModel(_args?: unknown): { type: string } {
  return { type: "cycle_model" };
}

/**
 * Build a set_thinking_level command. Args: {level}.
 * Spec: {type:"set_thinking_level", level}
 */
function buildSetThinkingLevel(args?: unknown): { type: string; level?: string } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; level?: string } = {
    type: "set_thinking_level",
  };
  const level = str(data.level);
  if (level) result.level = level;
  return result;
}

/**
 * Build a cycle_thinking_level command. No args.
 * Spec: {type:"cycle_thinking_level"}
 */
function buildCycleThinkingLevel(_args?: unknown): { type: string } {
  return { type: "cycle_thinking_level" };
}

/**
 * Build a set_steering_mode command. Args: {mode}.
 * Spec: {type:"set_steering_mode", mode}
 */
function buildSetSteeringMode(args?: unknown): { type: string; mode?: string } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; mode?: string } = {
    type: "set_steering_mode",
  };
  const mode = str(data.mode);
  if (mode) result.mode = mode;
  return result;
}

/**
 * Build a set_follow_up_mode command. Args: {mode}.
 * Spec: {type:"set_follow_up_mode", mode}
 */
function buildSetFollowUpMode(args?: unknown): { type: string; mode?: string } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; mode?: string } = {
    type: "set_follow_up_mode",
  };
  const mode = str(data.mode);
  if (mode) result.mode = mode;
  return result;
}

/**
 * Build a set_auto_compaction command. Args: {enabled}.
 * Spec: {type:"set_auto_compaction", enabled}
 */
function buildSetAutoCompaction(args?: unknown): { type: string; enabled?: boolean } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; enabled?: boolean } = {
    type: "set_auto_compaction",
  };
  const enabled = bool(data.enabled);
  if (enabled !== null) result.enabled = enabled;
  return result;
}

/**
 * Build a set_auto_retry command. Args: {enabled}.
 * Spec: {type:"set_auto_retry", enabled}
 */
function buildSetAutoRetry(args?: unknown): { type: string; enabled?: boolean } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; enabled?: boolean } = {
    type: "set_auto_retry",
  };
  const enabled = bool(data.enabled);
  if (enabled !== null) result.enabled = enabled;
  return result;
}

/**
 * Build a set_session_name command. Args: {name}.
 * Spec: {type:"set_session_name", name}
 */
function buildSetSessionName(args?: unknown): { type: string; name?: string } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; name?: string } = {
    type: "set_session_name",
  };
  const name = str(data.name);
  if (name) result.name = name;
  return result;
}

// ── Step 3d: Heavy/destructive command builders ───────────────────────────────

/**
 * Build a `bash` RPC command.
 * Spec: {type: "bash", command: string, workingDirectory?: string, environment?: Record<string, string>}
 */
function buildBashCommand(args?: unknown): { type: string; command: string; workingDirectory?: string; environment?: Record<string, string> } {
  const data = isRecord(args) ? args : {};
  const command = str(data.command);
  if (!command) {
    throw new Error("bash command requires 'command' argument");
  }
  const result: { type: string; command: string; workingDirectory?: string; environment?: Record<string, string> } = {
    type: "bash",
    command,
  };
  const workingDirectory = str(data.workingDirectory);
  if (workingDirectory) {
    result.workingDirectory = workingDirectory;
  }
  if (isRecord(data.environment)) {
    result.environment = {};
    for (const [key, value] of Object.entries(data.environment)) {
      if (typeof value === "string") {
        result.environment[key] = value;
      }
    }
  }
  return result;
}

/**
 * Build a `compact` RPC command.
 * Spec: {type: "compact", customInstructions?: string}
 */
function buildCompactCommand(args?: unknown): { type: string; customInstructions?: string } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; customInstructions?: string } = {
    type: "compact",
  };
  const customInstructions = str(data.customInstructions ?? data.reason);
  if (customInstructions) {
    result.customInstructions = customInstructions;
  }
  return result;
}

/**
 * Build a `fork` RPC command.
 * Spec: {type: "fork", entryId?: string}
 */
function buildForkCommand(args?: unknown): { type: string; entryId?: string; session_id?: string } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; entryId?: string; session_id?: string } = {
    type: "fork",
  };
  const entryId = str(data.entryId);
  if (entryId) {
    result.entryId = entryId;
  }
  const sessionId = str(data.sessionId ?? data.session_id);
  if (sessionId) {
    result.session_id = sessionId;
  }
  return result;
}

/**
 * Build a `clone` RPC command.
 * Spec: {type: "clone"}
 */
function buildCloneCommand(args?: unknown): { type: string; session_id?: string } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; session_id?: string } = {
    type: "clone",
  };
  const sessionId = str(data.sessionId ?? data.session_id);
  if (sessionId) {
    result.session_id = sessionId;
  }
  return result;
}

/**
 * Build a `export_html` RPC command.
 * Spec: {type: "export_html", outputPath?: string}
 */
function buildExportHtmlCommand(args?: unknown): { type: string; outputPath?: string } {
  const data = isRecord(args) ? args : {};
  const result: { type: string; outputPath?: string } = {
    type: "export_html",
  };
  const outputPath = str(data.outputPath);
  if (outputPath) {
    result.outputPath = outputPath;
  }
  return result;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function str(val: unknown): string | null {
  return typeof val === "string" && val.length > 0 ? val : null;
}

function bool(val: unknown): boolean | null {
  return typeof val === "boolean" ? val : null;
}
