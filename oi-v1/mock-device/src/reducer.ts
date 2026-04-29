import { EVENT_PROJECTIONS, logUnknownEventOnce } from "./pi_rpc_events.ts";
import type {
  ActionFrame,
  CommandSummary,
  Direction,
  EventFrame,
  FrontendState,
  LastActionResult,
  PromptState,
  PromptSummary,
  QueueHealth,
  ReducerFrame,
  SessionSummary,
  SnapshotData,
  View,
} from "./types.ts";

const EMPTY_PROMPT: PromptState = {
  pending: false,
  prompt_id: null,
  session_id: null,
  title: null,
  body: null,
  options: [],
};

const EMPTY_QUEUE_HEALTH: QueueHealth = {
  oldest_pending_prompt_age_s: null,
  oldest_queued_command_age_s: null,
};

const EMPTY_RESULT: LastActionResult = {
  ok: true,
  code: null,
  message: null,
};

export function initialState(): FrontendState {
  return {
    view: "idle",
    sessions: {
      active_session_id: null,
      list: [],
    },
    prompt: { ...EMPTY_PROMPT },
    prompts: [],
    queue_health: { ...EMPTY_QUEUE_HEALTH },
    queued_commands: [],
    device_hint: {
      response_pace_hint: null,
    },
    last_action_result: { ...EMPTY_RESULT },
  };
}

export function reducer(state: FrontendState, frame: ReducerFrame): FrontendState {
  switch (frame.type) {
    case "snapshot":
      return applySnapshot(state, frame.data);
    case "event":
      return applyEvent(state, frame);
    case "action":
      return applyAction(state, frame);
    case "expect":
      return state;
    default:
      return state;
  }
}

export function applySnapshot(state: FrontendState, data: SnapshotData): FrontendState {
  const sessionList = normaliseSessions(data.sessions?.list ?? data.sessions?.sessions ?? state.sessions.list);
  const activeSessionId = data.sessions?.active_session_id ?? state.sessions.active_session_id;

  const prompts = normalisePrompts(
    data.prompts ?? (data.prompt ? promptStateToSummary(data.prompt) : []),
  );

  const next: FrontendState = {
    ...state,
    sessions: {
      active_session_id: activeSessionId,
      list: sessionList,
    },
    prompts,
    queue_health: {
      ...EMPTY_QUEUE_HEALTH,
      ...data.queue_health,
    },
    queued_commands: [...(data.queued_commands ?? [])],
    device_hint: {
      response_pace_hint: data.device_hint?.response_pace_hint ?? null,
    },
    last_action_result: {
      ...state.last_action_result,
      ...data.last_action_result,
    },
  };

  return withDerivedPromptAndView(next, data.view);
}

function applyAction(state: FrontendState, action: ActionFrame): FrontendState {
  switch (action.name) {
    case "session.focus":
      return focusSession(state, stringValue(action.data?.session_id));
    case "session.cycle":
      return cycleSession(state, directionValue(action.data?.direction));
    case "prompt.answer":
      return answerPrompt(state, stringValue(action.data?.prompt_id), stringValue(action.data?.value));
    case "command.queue":
      return queueCommand(state, action.data ?? {});
    case "command.cancel":
      return cancelCommand(state, action.data ?? {});
    case "command.cancel_all":
      return cancelAllCommands(state, action.data ?? {});
    case "session.cleanup":
      return sessionCleanup(state, action.data ?? {});
    case "healthcheck":
      return healthcheck(state, action.data ?? {});
    default:
      return {
        ...state,
        last_action_result: failure("unsupported_action", `unsupported action: ${action.name}`),
      };
  }
}

function applyEvent(state: FrontendState, event: EventFrame): FrontendState {
  // Internal reducer events (from command.queue, prompt.pending, session.updated):
  // These are NOT Pi RPC events and are NOT in EVENT_PROJECTIONS.
  const data = event.data ?? {};
  switch (event.name) {
    case "prompt.pending":
    case "prompt.created": {
      const prompt = normalisePrompt(data);
      if (!prompt) {
        return { ...state, last_action_result: failure("validation_error", "invalid prompt event") };
      }
      const prompts = upsertById(state.prompts, prompt, "prompt_id");
      return withDerivedPromptAndView({ ...state, prompts });
    }
    case "prompt.answered":
    case "prompt.cancelled": {
      const promptId = stringValue(data.prompt_id);
      if (!promptId) {
        return { ...state, last_action_result: failure("validation_error", "prompt_id required") };
      }
      const prompts = state.prompts.filter((p) => p.prompt_id !== promptId);
      return withDerivedPromptAndView({ ...state, prompts });
    }
    case "command.queued": {
      const command = normaliseCommand(data);
      if (!command) {
        return { ...state, last_action_result: failure("validation_error", "invalid command event") };
      }
      return {
        ...state,
        queued_commands: upsertById(state.queued_commands, command, "command_id"),
        last_action_result: success("command_queued", `queued ${command.command_id}`),
      };
    }
    case "command.acked": {
      const commandId = stringValue(data.command_id);
      if (!commandId) {
        return { ...state, last_action_result: failure("validation_error", "command_id required") };
      }
      return {
        ...state,
        queued_commands: state.queued_commands.map((c) =>
          c.command_id === commandId ? { ...c, status: "acked" } : c,
        ),
        last_action_result: success("command_acked", `acked ${commandId}`),
      };
    }
    case "session.updated": {
      const session = normaliseSession(data);
      if (!session) {
        return { ...state, last_action_result: failure("validation_error", "invalid session event") };
      }
      const sessions = upsertById(state.sessions.list, session, "session_id");
      const active_session_id = state.sessions.active_session_id ?? session.session_id;
      return withDerivedPromptAndView({ ...state, sessions: { active_session_id, list: sessions } });
    }
    default:
      break;
  }

  // Pi RPC events delegate to EVENT_PROJECTIONS
  const projection = EVENT_PROJECTIONS[event.name];
  if (!projection) {
    logUnknownEventOnce(event.name);
    return state;
  }
  return projection(state, data) as FrontendState;
}

function focusSession(state: FrontendState, sessionId: string | null): FrontendState {
  if (!sessionId) {
    return { ...state, last_action_result: failure("validation_error", "session_id required") };
  }
  if (!state.sessions.list.some((session) => session.session_id === sessionId)) {
    return { ...state, last_action_result: failure("session_not_found", `unknown session: ${sessionId}`) };
  }
  return withDerivedPromptAndView({
    ...state,
    sessions: { ...state.sessions, active_session_id: sessionId },
    view: "idle",
    last_action_result: success("session_focused", `focused ${sessionId}`),
  });
}

function cycleSession(state: FrontendState, direction: Direction): FrontendState {
  const sessions = state.sessions.list;
  if (sessions.length === 0) {
    return withDerivedPromptAndView({
      ...state,
      sessions: { ...state.sessions, active_session_id: null },
      view: "idle",
      last_action_result: success("session_cycle_empty", "no sessions"),
    });
  }

  const currentIndex = sessions.findIndex((session) => session.session_id === state.sessions.active_session_id);
  const baseIndex = currentIndex >= 0 ? currentIndex : 0;
  const delta = direction === "prev" ? -1 : 1;
  const nextIndex = (baseIndex + delta + sessions.length) % sessions.length;
  const nextSessionId = sessions[nextIndex].session_id;

  return withDerivedPromptAndView({
    ...state,
    sessions: { ...state.sessions, active_session_id: nextSessionId },
    view: "idle",
    last_action_result: success("session_cycled", `focused ${nextSessionId}`),
  });
}

function answerPrompt(state: FrontendState, promptId: string | null, value: string | null): FrontendState {
  if (!promptId || value === null) {
    return { ...state, last_action_result: failure("validation_error", "prompt_id and value required") };
  }
  const promptExists = state.prompts.some((prompt) => prompt.prompt_id === promptId);
  if (!promptExists) {
    return { ...state, last_action_result: failure("prompt_not_found", `unknown prompt: ${promptId}`) };
  }
  const prompts = state.prompts.filter((prompt) => prompt.prompt_id !== promptId);
  const sessions = decrementPendingCount(state.sessions.list, promptId, state.prompts);
  return withDerivedPromptAndView({
    ...state,
    sessions: { ...state.sessions, list: sessions },
    prompts,
    view: "idle",
    last_action_result: success("prompt_answered", `answered ${promptId} with ${value}`),
  });
}

function cancelCommand(state: FrontendState, data: Record<string, unknown>): FrontendState {
  const commandId = stringValue(data.command_id);
  if (!commandId) {
    return { ...state, last_action_result: failure("validation_error", "command_id required") };
  }
  const command = state.queued_commands.find((c) => c.command_id === commandId);
  if (!command) {
    return { ...state, last_action_result: failure("command_not_found", `unknown command: ${commandId}`) };
  }
  if (command.status === "queued") {
    const queued_commands = state.queued_commands.filter((c) => c.command_id !== commandId);
    const sessions = decrementPendingCountFromCommand(state.sessions.list, command);
    return withDerivedPromptAndView({
      ...state,
      sessions: { ...state.sessions, list: sessions },
      prompts: state.prompts,
      queued_commands,
      last_action_result: success("command_cancelled", `cancelled ${commandId}`),
    });
  }
  return { ...state, last_action_result: success("command_unchanged", `command ${commandId} already ${command.status}`) };
}

function cancelAllCommands(state: FrontendState, data: Record<string, unknown>): FrontendState {
  const sessionId = stringValue(data.session_id);
  const dryRun = data.dry_run === true;

  const targetCommands = sessionId
    ? state.queued_commands.filter((c) => c.session_id === sessionId && c.status === "queued")
    : state.queued_commands.filter((c) => c.status === "queued");

  const inspected = sessionId
    ? state.queued_commands.filter((c) => c.session_id === sessionId).length
    : state.queued_commands.length;

  if (dryRun) {
    return {
      ...state,
      last_action_result: {
        ok: true,
        code: "command_cancel_all_dry_run",
        message: `would cancel ${targetCommands.length} of ${inspected} commands`,
      },
    };
  }

  const cancelledIds = new Set(targetCommands.map((c) => c.command_id));
  const queued_commands = state.queued_commands.filter((c) => !cancelledIds.has(c.command_id));
  const cancelled = cancelledIds.size;

  return {
    ...state,
    queued_commands,
    last_action_result: success(
      "command_cancel_all",
      `cancelled ${cancelled} of ${inspected} commands`,
    ),
  };
}

function sessionCleanup(state: FrontendState, data: Record<string, unknown>): FrontendState {
  const sessionId = stringValue(data.session_id) ?? state.sessions.active_session_id;
  const dryRun = data.dry_run === true;

  if (!sessionId) {
    return { ...state, last_action_result: failure("validation_error", "session_id required (no active session)") };
  }

  const sessionPrompts = state.prompts.filter(
    (p) => p.session_id === sessionId && (p.status ?? "pending") === "pending",
  );
  const sessionCommands = state.queued_commands.filter(
    (c) => c.session_id === sessionId && c.status === "queued",
  );

  const promptInspected = state.prompts.filter((p) => p.session_id === sessionId).length;
  const commandInspected = state.queued_commands.filter((c) => c.session_id === sessionId).length;

  if (dryRun) {
    return {
      ...state,
      last_action_result: {
        ok: true,
        code: "session_cleanup_dry_run",
        message: JSON.stringify({
          cancel_prompts: { cancelled: sessionPrompts.length, inspected: promptInspected, dry_run: true },
          cancel_commands: { cancelled: sessionCommands.length, inspected: commandInspected, dry_run: true },
          dry_run: true,
        }),
      },
    };
  }

  const promptIds = new Set(sessionPrompts.map((p) => p.prompt_id));
  const commandIds = new Set(sessionCommands.map((c) => c.command_id));

  const prompts = state.prompts.filter((p) => !promptIds.has(p.prompt_id));
  const queued_commands = state.queued_commands.filter((c) => !commandIds.has(c.command_id));
  const sessions = decrementSessionPendingCounts(state.sessions.list, sessionId, sessionPrompts.length);

  return withDerivedPromptAndView({
    ...state,
    sessions: { ...state.sessions, list: sessions },
    prompts,
    queued_commands,
    last_action_result: {
      ok: true,
      code: "session_cleanup",
      message: JSON.stringify({
        cancel_prompts: { cancelled: sessionPrompts.length, inspected: promptInspected },
        cancel_commands: { cancelled: sessionCommands.length, inspected: commandInspected },
        dry_run: false,
      }),
    },
  });
}

function healthcheck(state: FrontendState, data: Record<string, unknown>): FrontendState {
  const maxOldestPromptS = numberValue(data.max_oldest_prompt_s);
  const maxOldestCommandS = numberValue(data.max_oldest_command_s);
  const maxStaleSessions = numberValue(data.max_stale_sessions);

  const violations: string[] = [];

  if (maxOldestPromptS !== null && state.queue_health.oldest_pending_prompt_age_s !== null) {
    if (state.queue_health.oldest_pending_prompt_age_s > maxOldestPromptS) {
      violations.push(
        `oldest_pending_prompt_age_s=${state.queue_health.oldest_pending_prompt_age_s} > ${maxOldestPromptS}`,
      );
    }
  }

  if (maxOldestCommandS !== null && state.queue_health.oldest_queued_command_age_s !== null) {
    if (state.queue_health.oldest_queued_command_age_s > maxOldestCommandS) {
      violations.push(
        `oldest_queued_command_age_s=${state.queue_health.oldest_queued_command_age_s} > ${maxOldestCommandS}`,
      );
    }
  }

  if (maxStaleSessions !== null) {
    const staleCount = state.sessions.list.filter((s) => s.stale).length;
    if (staleCount > maxStaleSessions) {
      violations.push(`stale_sessions=${staleCount} > ${maxStaleSessions}`);
    }
  }

  const ok = violations.length === 0;
  return {
    ...state,
    last_action_result: {
      ok,
      code: ok ? "healthcheck_ok" : "healthcheck_violations",
      message: violations.length > 0 ? violations.join("; ") : "no violations",
    },
  };
}

function decrementPendingCountFromCommand(
  sessions: SessionSummary[],
  command: CommandSummary,
): SessionSummary[] {
  return sessions.map((s) => {
    if (s.session_id !== command.session_id || s.pending_count <= 0) return s;
    return { ...s, pending_count: Math.max(0, s.pending_count - 1) };
  });
}

function decrementSessionPendingCounts(
  sessions: SessionSummary[],
  sessionId: string,
  count: number,
): SessionSummary[] {
  return sessions.map((s) => {
    if (s.session_id !== sessionId) return s;
    return { ...s, pending_count: Math.max(0, s.pending_count - count) };
  });
}

function queueCommand(state: FrontendState, data: Record<string, unknown>): FrontendState {
  const sessionId = stringValue(data.session_id) ?? state.sessions.active_session_id;
  const verb = stringValue(data.verb);
  if (!sessionId || !verb) {
    return { ...state, last_action_result: failure("validation_error", "session_id and verb required") };
  }
  if (!state.sessions.list.some((session) => session.session_id === sessionId)) {
    return { ...state, last_action_result: failure("session_not_found", `unknown session: ${sessionId}`) };
  }

  const requestId = stringValue(data.request_id);
  const commandId = stringValue(data.command_id) ?? requestId ?? `local-${state.queued_commands.length + 1}`;
  const command: CommandSummary = {
    command_id: commandId,
    session_id: sessionId,
    verb,
    status: "queued",
    request_id: requestId,
  };

  return {
    ...state,
    queued_commands: upsertById(state.queued_commands, command, "command_id"),
    last_action_result: success("command_queued", `queued ${verb}`),
  };
}

function withDerivedPromptAndView(state: FrontendState, requestedView?: View): FrontendState {
  const prompt = activePromptState(state.prompts, state.sessions.active_session_id);
  const view = prompt.pending ? "prompt" : requestedView ?? (state.view === "prompt" ? "idle" : state.view);
  return {
    ...state,
    prompt,
    view,
  };
}

function activePromptState(prompts: PromptSummary[], activeSessionId: string | null): PromptState {
  const activePrompt = prompts.find((prompt) =>
    prompt.session_id === activeSessionId && (prompt.status ?? "pending") === "pending",
  );
  if (!activePrompt) {
    return { ...EMPTY_PROMPT };
  }
  return {
    pending: true,
    prompt_id: activePrompt.prompt_id,
    session_id: activePrompt.session_id,
    title: activePrompt.title,
    body: activePrompt.body,
    options: activePrompt.options,
  };
}

function normaliseSessions(sessions: SessionSummary[]): SessionSummary[] {
  return sessions.map((session) => normaliseSession(session)).filter((session): session is SessionSummary => session !== null);
}

function normaliseSession(value: unknown): SessionSummary | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const data = value as Record<string, unknown>;
  const sessionId = stringValue(data.session_id);
  if (!sessionId) {
    return null;
  }
  return {
    session_id: sessionId,
    name: stringValue(data.name) ?? sessionId,
    status: stringValue(data.status) ?? "unknown",
    pending_count: numberValue(data.pending_count) ?? 0,
    stale: booleanValue(data.stale) ?? false,
    last_seen_age_s: numberValue(data.last_seen_age_s),
  };
}

function normalisePrompts(prompts: PromptSummary[]): PromptSummary[] {
  return prompts.map((prompt) => normalisePrompt(prompt)).filter((prompt): prompt is PromptSummary => prompt !== null);
}

function normalisePrompt(value: unknown): PromptSummary | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const data = value as Record<string, unknown>;
  const promptId = stringValue(data.prompt_id) ?? stringValue(data.id);
  if (!promptId) {
    return null;
  }
  const rawOptions = Array.isArray(data.options) ? data.options : [];
  const options = rawOptions
    .map((option) => {
      if (typeof option !== "object" || option === null) {
        return null;
      }
      const opt = option as Record<string, unknown>;
      const label = stringValue(opt.label);
      const val = stringValue(opt.value);
      return label !== null && val !== null ? { label, value: val } : null;
    })
    .filter((option): option is { label: string; value: string } => option !== null);
  return {
    prompt_id: promptId,
    session_id: stringValue(data.session_id),
    title: stringValue(data.title),
    body: stringValue(data.body),
    options,
    status: stringValue(data.status) ?? "pending",
  };
}

function promptStateToSummary(prompt: Partial<PromptState>): PromptSummary[] {
  if (!prompt.pending || !prompt.prompt_id) {
    return [];
  }
  return [{
    prompt_id: prompt.prompt_id,
    session_id: prompt.session_id ?? null,
    title: prompt.title ?? null,
    body: prompt.body ?? null,
    options: prompt.options ?? [],
    status: "pending",
  }];
}

function normaliseCommand(value: unknown): CommandSummary | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const data = value as Record<string, unknown>;
  const commandId = stringValue(data.command_id);
  const sessionId = stringValue(data.session_id);
  const verb = stringValue(data.verb);
  if (!commandId || !sessionId || !verb) {
    return null;
  }
  return {
    command_id: commandId,
    session_id: sessionId,
    verb,
    status: stringValue(data.status) ?? "queued",
    request_id: stringValue(data.request_id),
  };
}

function decrementPendingCount(
  sessions: SessionSummary[],
  promptId: string,
  prompts: PromptSummary[],
): SessionSummary[] {
  const prompt = prompts.find((candidate) => candidate.prompt_id === promptId);
  if (!prompt?.session_id) {
    return sessions;
  }
  return sessions.map((session) => {
    if (session.session_id !== prompt.session_id) {
      return session;
    }
    return { ...session, pending_count: Math.max(0, session.pending_count - 1) };
  });
}

function directionValue(value: unknown): Direction {
  return value === "prev" ? "prev" : "next";
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

function upsertById<T, K extends keyof T>(items: T[], item: T, key: K): T[] {
  const found = items.some((candidate) => candidate[key] === item[key]);
  if (!found) {
    return [...items, item];
  }
  return items.map((candidate) => candidate[key] === item[key] ? item : candidate);
}

function success(code: string, message: string): LastActionResult {
  return { ok: true, code, message };
}

function failure(code: string, message: string): LastActionResult {
  return { ok: false, code, message };
}
