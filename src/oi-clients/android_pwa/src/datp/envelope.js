const DATP_VERSION = 'datp';

export function nowIso(date = new Date()) {
  return date.toISOString().replace(/\.\d{3}Z$/, (match) => match);
}

export function newId(prefix = 'msg', random = Math.random) {
  const value = Math.floor(random() * Number.MAX_SAFE_INTEGER).toString(16).padStart(12, '0');
  return `${prefix}_${value.slice(0, 12)}`;
}

export function buildEnvelope({ type, deviceId, payload = {}, id = newId(type.slice(0, 4)), ts = nowIso() }) {
  if (!type) throw new TypeError('type is required');
  if (!deviceId) throw new TypeError('deviceId is required');
  return { v: DATP_VERSION, type, id, device_id: deviceId, ts, payload };
}

export function buildHello({ deviceId, deviceName = 'Samsung A10', firmware = 'oi-android-pwa/0.1', capabilities = {}, state = { mode: 'READY' }, conversation }) {
  const payload = {
    device_type: 'android_pwa',
    device_name: deviceName,
    protocol: DATP_VERSION,
    firmware,
    capabilities: {
      mic: true,
      speaker: true,
      display: true,
      buttons: true,
      touch: true,
      ...capabilities,
    },
    state,
  };
  if (conversation && Object.keys(conversation).length) payload.conversation = conversation;
  return buildEnvelope({ type: 'hello', deviceId, payload, id: newId('hello') });
}

export function buildAck(deviceId, commandId, ok = true) {
  return buildEnvelope({ type: 'ack', deviceId, payload: { command_id: commandId, ok }, id: newId('ack') });
}

export function buildEvent(deviceId, event, fields = {}) {
  return buildEnvelope({ type: 'event', deviceId, payload: { event, ...fields }, id: newId('evt') });
}

export function buildState(deviceId, mode, fields = {}) {
  return buildEnvelope({ type: 'state', deviceId, payload: { mode, ...fields }, id: newId('stat') });
}

export function buildAudioChunk(deviceId, { streamId, seq, pcm16, sampleRate = 16000, channels = 1 }) {
  if (!streamId) throw new TypeError('streamId is required');
  if (!Number.isInteger(seq) || seq < 0) throw new TypeError('seq must be a non-negative integer');
  return buildEnvelope({
    type: 'audio_chunk',
    deviceId,
    id: newId('aud'),
    payload: {
      stream_id: streamId,
      seq,
      format: 'pcm16',
      sample_rate: sampleRate,
      channels,
      data_b64: bytesToBase64(pcm16),
    },
  });
}

export function parseDatp(raw) {
  const message = typeof raw === 'string' ? JSON.parse(raw) : raw;
  for (const field of ['v', 'type', 'id', 'device_id', 'ts', 'payload']) {
    if (!(field in message)) throw new Error(`Missing required field: ${field}`);
  }
  if (message.v !== DATP_VERSION) throw new Error(`Unsupported DATP version: ${message.v}`);
  return message;
}

export function bytesToBase64(bytes) {
  if (bytes instanceof ArrayBuffer) bytes = new Uint8Array(bytes);
  if (ArrayBuffer.isView(bytes)) {
    let binary = '';
    for (const byte of new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength)) binary += String.fromCharCode(byte);
    return btoa(binary);
  }
  if (typeof bytes === 'string') return btoa(bytes);
  throw new TypeError('bytes must be an ArrayBuffer, typed array, or binary string');
}

export function base64ToBytes(value) {
  const binary = atob(value || '');
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}
