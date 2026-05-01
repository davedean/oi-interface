import test from 'node:test';
import assert from 'node:assert/strict';
import { AudioPlayback, pcm16WavBlob } from '../../src/audio/playback.js';

test('unlock warms browser audio during user gesture', async () => {
  const calls = [];
  const playback = new AudioPlayback({
    AudioContextImpl: class { async resume() { calls.push('resume'); } },
    audioFactory: () => ({ play: async () => calls.push('warm-play'), pause: () => calls.push('warm-pause') }),
  });
  await playback.unlock();
  assert.equal(playback.unlocked, true);
  assert.deepEqual(calls, ['resume', 'warm-play', 'warm-pause']);
});

test('playback requires user gesture unlock', async () => {
  const playback = new AudioPlayback({ audioFactory: () => ({ play: async () => {}, pause() {} }) });
  await assert.rejects(() => playback.play({ pcm: new Uint8Array([0, 0]) }), /locked/);
  await playback.unlock();
  const audio = await playback.play({ pcm: new Uint8Array([0, 0]), sampleRate: 16000 });
  assert.match(audio.src, /^blob:/);
});

test('unlock tolerates a rejected warm-up and lets real play surface later errors', async () => {
  const playback = new AudioPlayback({ audioFactory: () => ({ play: async () => { throw new Error('blocked'); }, pause() {} }) });
  await playback.unlock();
  assert.equal(playback.unlocked, true);
  await assert.rejects(() => playback.play({ pcm: new Uint8Array([0, 0]) }), /blocked/);
});

test('stop pauses current audio and rewinds', async () => {
  const audio = { currentTime: 5, play: async () => {}, pauseCalled: false, pause() { this.pauseCalled = true; } };
  const playback = new AudioPlayback({ audioFactory: () => audio });
  await playback.unlock();
  await playback.play({ pcm: new Uint8Array([0, 0]) });
  playback.stop();
  assert.equal(audio.pauseCalled, true);
  assert.equal(audio.currentTime, 0);
});

test('pcm16WavBlob creates a wav blob with riff header', async () => {
  const blob = pcm16WavBlob(new Uint8Array([1, 2, 3, 4]), 16000);
  assert.equal(blob.type, 'audio/wav');
  const bytes = new Uint8Array(await blob.arrayBuffer());
  assert.equal(String.fromCharCode(...bytes.slice(0, 4)), 'RIFF');
  assert.equal(String.fromCharCode(...bytes.slice(8, 12)), 'WAVE');
});
