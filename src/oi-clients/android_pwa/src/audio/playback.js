export class AudioPlayback {
  constructor({ audioFactory = () => new Audio(), AudioContextImpl = globalThis.AudioContext || globalThis.webkitAudioContext } = {}) {
    this.audioFactory = audioFactory;
    this.AudioContextImpl = AudioContextImpl;
    this.context = null;
    this.unlocked = false;
    this.current = null;
  }

  async unlock() {
    if (this.unlocked) return true;
    if (this.AudioContextImpl) {
      this.context = this.context || new this.AudioContextImpl();
      await this.context.resume?.();
    }
    const audio = this.audioFactory();
    audio.muted = true;
    audio.src = silentWavDataUrl();
    try {
      await audio.play?.();
      audio.pause?.();
    } catch {
      // Some browsers still reject the warm-up. Keep the explicit gesture
      // attempt, but let the real play surface any remaining policy failure.
    }
    this.unlocked = true;
    return true;
  }

  async play(response) {
    if (!this.unlocked) throw new Error('Audio playback is locked until a user gesture');
    if (!response || !response.pcm) throw new Error('No cached audio response');
    const audio = this.audioFactory();
    audio.src = URL.createObjectURL(pcm16WavBlob(response.pcm, response.sampleRate || 22050));
    this.current = audio;
    await audio.play();
    return audio;
  }

  stop() {
    if (!this.current) return;
    this.current.pause();
    this.current.currentTime = 0;
  }
}

export function pcm16WavBlob(pcmBytes, sampleRate = 22050) {
  const header = new ArrayBuffer(44);
  const view = new DataView(header);
  writeAscii(view, 0, 'RIFF');
  view.setUint32(4, 36 + pcmBytes.byteLength, true);
  writeAscii(view, 8, 'WAVEfmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, 'data');
  view.setUint32(40, pcmBytes.byteLength, true);
  return new Blob([header, pcmBytes], { type: 'audio/wav' });
}

function silentWavDataUrl() {
  const bytes = new Uint8Array([82,73,70,70,38,0,0,0,87,65,86,69,102,109,116,32,16,0,0,0,1,0,1,0,64,31,0,0,128,62,0,0,2,0,16,0,100,97,116,97,2,0,0,0,0,0]);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return `data:audio/wav;base64,${btoa(binary)}`;
}

function writeAscii(view, offset, text) {
  for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
}
