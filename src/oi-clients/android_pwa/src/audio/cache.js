import { base64ToBytes } from '../datp/envelope.js';

export class AudioCache {
  constructor({ maxResponses = 8 } = {}) {
    this.maxResponses = maxResponses;
    this.responses = new Map();
    this.latestId = null;
  }

  begin({ response_id: responseId, format = 'wav_pcm16', sample_rate: sampleRate = 22050 }) {
    if (!responseId) throw new Error('response_id is required');
    this.responses.set(responseId, { responseId, format, sampleRate, chunks: new Map(), complete: false });
    this.latestId = responseId;
    this._evict();
  }

  putChunk({ response_id: responseId, seq, data_b64: dataB64 }) {
    const response = this._require(responseId);
    if (!Number.isInteger(seq) || seq < 0) throw new Error('invalid audio chunk sequence');
    response.chunks.set(seq, base64ToBytes(dataB64));
  }

  end({ response_id: responseId }) {
    const response = this._require(responseId);
    const expected = response.chunks.size ? Math.max(...response.chunks.keys()) + 1 : 0;
    for (let seq = 0; seq < expected; seq += 1) if (!response.chunks.has(seq)) throw new Error(`missing audio chunk ${seq}`);
    response.complete = true;
    return this.get(responseId);
  }

  get(responseId = 'latest') {
    const id = responseId === 'latest' ? this.latestId : responseId;
    if (!id || !this.responses.has(id)) return null;
    const response = this.responses.get(id);
    const chunks = [...response.chunks.keys()].sort((a, b) => a - b).map((seq) => response.chunks.get(seq));
    return { ...response, chunks, pcm: concatBytes(chunks) };
  }

  _require(responseId) {
    const response = this.responses.get(responseId);
    if (!response) throw new Error(`unknown audio response: ${responseId}`);
    return response;
  }

  _evict() {
    while (this.responses.size > this.maxResponses) this.responses.delete(this.responses.keys().next().value);
  }
}

export function concatBytes(chunks) {
  const length = chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  const out = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { out.set(chunk, offset); offset += chunk.byteLength; }
  return out;
}
