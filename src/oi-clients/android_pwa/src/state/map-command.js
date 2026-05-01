const STATUS_MAP = {
  READY: 'idle', RECORDING: 'listening', UPLOADING: 'uploading', THINKING: 'thinking',
  RESPONSE_CACHED: 'response_cached', PLAYING: 'playing', MUTED: 'muted', OFFLINE: 'offline',
  ERROR: 'error', SAFE_MODE: 'safe_mode', idle: 'idle', listening: 'listening', uploading: 'uploading',
  thinking: 'thinking', response_cached: 'response_cached', playing: 'playing', confirm: 'confirm',
  muted: 'muted', offline: 'offline', error: 'error', safe_mode: 'safe_mode', task_running: 'task_running', blocked: 'blocked',
};

export function actionsForCommand(message) {
  const { op, args = {} } = message.payload || {};
  switch (op) {
    case 'display.show_status':
      return [{ type: 'state.set', status: normalizeStatus(args.state), label: args.label || args.state }];
    case 'display.show_progress':
      return [{ type: 'state.set', status: args.kind === 'blocked' ? 'blocked' : 'task_running', label: args.text || 'Working' }];
    case 'display.show_response_delta':
      return [args.is_final ? { type: 'text.final', text: args.text_delta || '' } : { type: 'text.delta', text: args.text_delta || '' }];
    case 'display.show_card':
      return [{ type: 'confirm.show', title: args.title, body: args.body, options: args.options || [] }];
    case 'audio.cache.put_begin':
      return [{ type: 'state.set', status: 'thinking', label: args.label || 'Caching audio' }];
    case 'audio.cache.put_end':
      return [{ type: 'state.set', status: 'response_cached', label: 'Response cached', responseId: args.response_id }];
    case 'audio.play':
      return [{ type: 'state.set', status: 'playing', label: 'Playing', responseId: args.response_id || 'latest' }];
    case 'audio.stop':
      return [{ type: 'state.set', status: 'idle', label: 'Idle' }];
    case 'device.mute_until':
      return [{ type: 'state.set', status: 'muted', label: 'Muted' }];
    default:
      return [];
  }
}

export function normalizeStatus(value) {
  const normalized = STATUS_MAP[value] || STATUS_MAP[String(value || '').toLowerCase()];
  return normalized || 'error';
}
