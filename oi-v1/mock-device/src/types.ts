export type View = "idle" | "session_list" | "prompt" | "command_menu" | "settings";

export interface SessionSummary {
  session_id: string;
  name: string;
  status: string;
  pending_count: number;
  stale: boolean;
  last_seen_age_s: number | null;
}

export interface PromptOption {
  label: string;
  value: string;
}

export interface PromptSummary {
  prompt_id: string;
  session_id: string | null;
  title: string | null;
  body: string | null;
  options: PromptOption[];
  status?: string;
}

export interface PromptState {
  pending: boolean;
  prompt_id: string | null;
  session_id: string | null;
  title: string | null;
  body: string | null;
  options: PromptOption[];
}

export interface SessionsState {
  active_session_id: string | null;
  list: SessionSummary[];
}

export interface QueueHealth {
  oldest_pending_prompt_age_s: number | null;
  oldest_queued_command_age_s: number | null;
}

export interface DeviceHint {
  response_pace_hint: string | null;
}

export interface LastActionResult {
  ok: boolean;
  code: string | null;
  message: string | null;
}

export interface CommandSummary {
  command_id: string;
  session_id: string;
  verb: string;
  status: string;
  request_id?: string | null;
}

export interface FrontendState {
  view: View;
  sessions: SessionsState;
  prompt: PromptState;
  prompts: PromptSummary[];
  queue_health: QueueHealth;
  queued_commands: CommandSummary[];
  device_hint: DeviceHint;
  last_action_result: LastActionResult;
}

export type Direction = "next" | "prev";

export type ReducerFrame = SnapshotFrame | EventFrame | ActionFrame | ExpectFrame;

export interface SnapshotFrame {
  type: "snapshot";
  data: SnapshotData;
}

export interface EventFrame {
  type: "event";
  name: string;
  data?: Record<string, unknown>;
}

export interface ActionFrame {
  type: "action";
  name: string;
  data?: Record<string, unknown>;
}

export interface ExpectFrame {
  type: "expect";
  data: Record<string, unknown>;
}

export interface SnapshotData {
  view?: View;
  sessions?: Partial<SessionsState> & { sessions?: SessionSummary[] };
  prompt?: Partial<PromptState> | null;
  prompts?: PromptSummary[];
  queue_health?: Partial<QueueHealth>;
  queued_commands?: CommandSummary[];
  device_hint?: Partial<DeviceHint>;
  last_action_result?: Partial<LastActionResult>;
}
