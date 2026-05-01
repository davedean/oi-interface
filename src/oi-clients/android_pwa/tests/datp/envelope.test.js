import test from 'node:test';
import assert from 'node:assert/strict';
import { buildAck, buildAudioChunk, buildEvent, buildHello, buildState, parseDatp, base64ToBytes } from '../../src/datp/envelope.js';

test('buildHello maps Android PWA registration to DATP hello', () => {
  const msg = buildHello({ deviceId: 'phone-1', capabilities: { battery: true } });
  assert.equal(msg.v, 'datp');
  assert.equal(msg.type, 'hello');
  assert.equal(msg.device_id, 'phone-1');
  assert.equal(msg.payload.device_type, 'android_pwa');
  assert.equal(msg.payload.capabilities.mic, true);
  assert.equal(msg.payload.capabilities.battery, true);
  assert.equal(msg.payload.state.mode, 'READY');
});

test('event, state, ack and audio chunk builders use gateway-compatible fields', () => {
  assert.deepEqual(buildEvent('d', 'input.mute.toggle').payload, { event: 'input.mute.toggle' });
  assert.deepEqual(buildState('d', 'UPLOADING').payload, { mode: 'UPLOADING' });
  assert.deepEqual(buildAck('d', 'cmd_1', false).payload, { command_id: 'cmd_1', ok: false });
  const audio = buildAudioChunk('d', { streamId: 's', seq: 2, pcm16: new Uint8Array([1, 2, 3]) });
  assert.equal(audio.type, 'audio_chunk');
  assert.equal(audio.payload.format, 'pcm16');
  assert.deepEqual([...base64ToBytes(audio.payload.data_b64)], [1, 2, 3]);
});

test('parseDatp validates required envelope fields and version', () => {
  const hello = buildHello({ deviceId: 'd' });
  assert.equal(parseDatp(JSON.stringify(hello)).type, 'hello');
  assert.throws(() => parseDatp('{'), /JSON/);
  assert.throws(() => parseDatp({ ...hello, v: 'other' }), /Unsupported/);
  const { id, ...missing } = hello;
  assert.throws(() => parseDatp(missing), /id/);
});
