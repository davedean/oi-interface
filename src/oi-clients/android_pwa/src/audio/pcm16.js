export function floatToPcm16(samples) {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i += 1) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

export function downsampleMono(input, inputRate, outputRate = 16000) {
  if (outputRate === inputRate) return Float32Array.from(input);
  if (outputRate > inputRate) throw new Error('outputRate must be <= inputRate');
  const ratio = inputRate / outputRate;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), input.length);
    let sum = 0;
    for (let j = start; j < end; j += 1) sum += input[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}


export function pcm16ToBytes(int16) {
  return new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength);
}
