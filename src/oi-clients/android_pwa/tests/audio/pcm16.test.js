import test from 'node:test';
import assert from 'node:assert/strict';
import { downsampleMono, floatToPcm16, interleavedToMono, pcm16ToBytes } from '../../src/audio/pcm16.js';

test('floatToPcm16 clamps and converts samples', () => {
  const pcm = floatToPcm16(Float32Array.from([-2, -1, 0, 1, 2]));
  assert.deepEqual([...pcm], [-32768, -32768, 0, 32767, 32767]);
  assert.equal(pcm16ToBytes(pcm).byteLength, 10);
});

test('downsampleMono averages source windows', () => {
  const out = downsampleMono(Float32Array.from([1, 3, 5, 7]), 4, 2);
  assert.deepEqual([...out], [2, 6]);
  assert.throws(() => downsampleMono(Float32Array.from([1]), 16000, 48000), /<=/);
});

test('interleavedToMono mixes channels', () => {
  assert.deepEqual([...interleavedToMono(Float32Array.from([1, 3, 5, 7]), 2)], [2, 6]);
  assert.deepEqual([...interleavedToMono(Float32Array.from([9]), 1)], [9]);
});
