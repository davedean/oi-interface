import test from 'node:test';
import assert from 'node:assert/strict';
import { PttRecorder } from '../../src/audio/recorder.js';

test('PTT recorder sends DATP events, chunks, and finished notification', async () => {
  const sent = [];
  const client = { sendEvent: (...args) => sent.push(['event', ...args]), sendState: (...args) => sent.push(['state', ...args]), sendAudioChunk: (...args) => sent.push(['audio', ...args]) };
  const navigatorRef = { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stopped: false, stop() { this.stopped = true; } }] }) } };
  let processor;
  class AudioContextStub {
    constructor() { this.sampleRate = 16000; this.destination = {}; }
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    createScriptProcessor() { processor = { connect() {}, disconnect() {} }; return processor; }
    async close() {}
  }
  let now = 100;
  const recorder = new PttRecorder({ client, navigatorRef, AudioContextImpl: AudioContextStub, clock: { now: () => now } });
  const streamId = await recorder.start();
  processor.onaudioprocess({ inputBuffer: { getChannelData: () => Float32Array.from([0, 0.5, -0.5, 1]) } });
  now = 275;
  await recorder.stop();
  assert.equal(sent[0][1], 'input.ptt.start');
  assert.equal(sent[1][1], 'RECORDING');
  assert.equal(sent[2][0], 'audio');
  assert.equal(sent[2][1].streamId, streamId);
  assert.equal(sent.at(-2)[1], 'audio.recording_finished');
  assert.equal(sent.at(-2)[2].duration_ms, 175);
  assert.equal(sent.at(-1)[1], 'UPLOADING');
});

test('PTT recorder guards unavailable and inactive states', async () => {
  const recorder = new PttRecorder({ client: {}, navigatorRef: {}, clock: { now: () => 0 } });
  await assert.rejects(() => recorder.start(), /Microphone/);
  assert.throws(() => recorder.pushSamples(Float32Array.from([0]), 16000), /not active/);
});
