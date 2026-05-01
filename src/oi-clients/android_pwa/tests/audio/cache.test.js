import test from 'node:test';
import assert from 'node:assert/strict';
import { AudioCache, concatBytes } from '../../src/audio/cache.js';

test('audio cache assembles ordered PCM and tracks latest', () => {
  const cache = new AudioCache();
  cache.begin({ response_id: 'r1', sample_rate: 22050 });
  cache.putChunk({ response_id: 'r1', seq: 1, data_b64: btoa(String.fromCharCode(3, 4)) });
  cache.putChunk({ response_id: 'r1', seq: 0, data_b64: btoa(String.fromCharCode(1, 2)) });
  const response = cache.end({ response_id: 'r1' });
  assert.equal(response.complete, true);
  assert.deepEqual([...response.pcm], [1, 2, 3, 4]);
  assert.equal(cache.get('latest').responseId, 'r1');
});

test('audio cache rejects missing and unknown chunks', () => {
  const cache = new AudioCache();
  assert.throws(() => cache.putChunk({ response_id: 'missing', seq: 0, data_b64: '' }), /unknown/);
  cache.begin({ response_id: 'r' });
  cache.putChunk({ response_id: 'r', seq: 1, data_b64: btoa('x') });
  assert.throws(() => cache.end({ response_id: 'r' }), /missing audio chunk 0/);
  assert.throws(() => cache.putChunk({ response_id: 'r', seq: -1, data_b64: '' }), /invalid/);
});

test('audio cache evicts old responses and concatenates bytes', () => {
  const cache = new AudioCache({ maxResponses: 1 });
  cache.begin({ response_id: 'old' });
  cache.begin({ response_id: 'new' });
  assert.equal(cache.get('old'), null);
  assert.deepEqual([...concatBytes([new Uint8Array([1]), new Uint8Array([2, 3])])], [1, 2, 3]);
});
