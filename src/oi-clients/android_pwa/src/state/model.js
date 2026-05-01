export const UI_STATES = Object.freeze([
  'idle', 'listening', 'uploading', 'thinking', 'response_cached', 'playing',
  'confirm', 'muted', 'offline', 'error', 'safe_mode', 'task_running', 'blocked',
]);

const VALID = new Set(UI_STATES);

export function createInitialState(overrides = {}) {
  return {
    status: 'offline',
    connected: false,
    muted: false,
    label: 'Offline',
    text: '',
    finalText: '',
    error: null,
    confirm: null,
    audioResponseId: null,
    debugOpen: false,
    events: [],
    ...overrides,
  };
}

export function reduceState(state, action) {
  switch (action.type) {
    case 'connection.online':
      return withEvent({ ...state, connected: true, status: state.status === 'offline' ? 'idle' : state.status, label: 'Connected', error: null }, action);
    case 'connection.offline':
      return withEvent({ ...state, connected: false, status: 'offline', label: 'Offline' }, action);
    case 'state.set':
      return withEvent(setStatus(state, action.status, action.label), action);
    case 'ptt.start':
      return withEvent(setStatus(state, 'listening', 'Listening'), action);
    case 'ptt.stop':
      return withEvent(setStatus(state, 'uploading', 'Uploading'), action);
    case 'mute.toggle':
      return withEvent({ ...state, muted: !state.muted, status: !state.muted ? 'muted' : 'idle', label: !state.muted ? 'Muted' : 'Idle' }, action);
    case 'text.delta':
      return withEvent({ ...state, text: `${state.text}${action.text || ''}`, status: state.status === 'idle' ? 'thinking' : state.status }, action);
    case 'text.final':
      return withEvent({ ...state, finalText: action.text ?? state.text, text: action.text ?? state.text, status: 'response_cached', label: 'Response ready' }, action);
    case 'confirm.show':
      return withEvent({ ...state, status: 'confirm', label: action.title || 'Confirm', confirm: { title: action.title, body: action.body, options: action.options || [] } }, action);
    case 'confirm.clear':
      return withEvent({ ...state, status: 'idle', label: 'Idle', confirm: null }, action);
    case 'error':
      return withEvent({ ...state, status: 'error', label: 'Error', error: action.error || 'Unknown error' }, action);
    case 'debug.toggle':
      return { ...state, debugOpen: !state.debugOpen };
    default:
      return state;
  }
}

export function setStatus(state, status, label = status) {
  if (!VALID.has(status)) throw new Error(`Unknown UI state: ${status}`);
  return { ...state, status, label };
}

function withEvent(state, action) {
  const event = { type: action.type, at: action.at || new Date().toISOString(), summary: action.summary || action.type };
  return { ...state, events: [event, ...state.events].slice(0, 80) };
}
