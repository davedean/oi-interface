import { downsampleMono, floatToPcm16, pcm16ToBytes } from './pcm16.js';

export class PttRecorder {
  constructor({ client, navigatorRef = globalThis.navigator, AudioContextImpl = globalThis.AudioContext || globalThis.webkitAudioContext, clock = globalThis.performance } = {}) {
    if (!client) throw new TypeError('client is required');
    this.client = client;
    this.navigator = navigatorRef;
    this.AudioContextImpl = AudioContextImpl;
    this.clock = clock;
    this.stream = null;
    this.context = null;
    this.source = null;
    this.processor = null;
    this.streamId = null;
    this.seq = 0;
    this.startedAt = 0;
    this.recording = false;
  }

  async start() {
    if (this.recording) return this.streamId;
    if (!this.navigator?.mediaDevices?.getUserMedia) throw new Error('Microphone capture is unavailable');
    this.stream = await this.navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    this.context = this.AudioContextImpl ? new this.AudioContextImpl() : null;
    if (this.context?.createMediaStreamSource && this.context?.createScriptProcessor) {
      this.source = this.context.createMediaStreamSource(this.stream);
      this.processor = this.context.createScriptProcessor(2048, 1, 1);
      this.processor.onaudioprocess = (event) => {
        const input = event.inputBuffer.getChannelData(0);
        this.pushSamples(input, this.context.sampleRate || 48000);
      };
      this.source.connect(this.processor);
      this.processor.connect(this.context.destination);
    }
    this.streamId = `pwa_${Date.now().toString(16)}`;
    this.seq = 0;
    this.startedAt = this.clock.now ? this.clock.now() : Date.now();
    this.recording = true;
    this.client.sendEvent('input.ptt.start', { stream_id: this.streamId });
    this.client.sendState('RECORDING');
    return this.streamId;
  }

  pushSamples(samples, sampleRate = 48000) {
    if (!this.recording) throw new Error('Recorder is not active');
    const mono16k = downsampleMono(samples, sampleRate, 16000);
    const pcm = pcm16ToBytes(floatToPcm16(mono16k));
    this.client.sendAudioChunk({ streamId: this.streamId, seq: this.seq, pcm16: pcm, sampleRate: 16000, channels: 1 });
    this.seq += 1;
  }

  async stop() {
    if (!this.recording) return;
    const endedAt = this.clock.now ? this.clock.now() : Date.now();
    const durationMs = Math.max(0, Math.round(endedAt - this.startedAt));
    this.processor?.disconnect?.();
    this.source?.disconnect?.();
    for (const track of this.stream?.getTracks?.() || []) track.stop();
    await this.context?.close?.();
    this.processor = null;
    this.source = null;
    this.client.sendEvent('input.ptt.stop', { stream_id: this.streamId });
    this.client.sendEvent('audio.recording_finished', { stream_id: this.streamId, duration_ms: durationMs, original_sample_rate: 16000, original_channels: 1 });
    this.client.sendState('UPLOADING');
    this.recording = false;
  }
}
