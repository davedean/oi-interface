import { buildAck, buildAudioChunk, buildEvent, buildHello, buildState, parseDatp } from './envelope.js';

export class DatpClient extends EventTarget {
  constructor({ url, deviceId = 'android-pwa-samsung-a10', deviceName = 'Samsung A10', WebSocketImpl = globalThis.WebSocket, timers = globalThis, reconnect = true, heartbeatMs = 15000 } = {}) {
    super();
    if (!url) throw new TypeError('url is required');
    if (!WebSocketImpl) throw new TypeError('WebSocket implementation is required');
    this.url = url;
    this.deviceId = deviceId;
    this.deviceName = deviceName;
    this.WebSocketImpl = WebSocketImpl;
    this.timers = timers;
    this.reconnect = reconnect;
    this.heartbeatMs = heartbeatMs;
    this.ws = null;
    this.connected = false;
    this._manualClose = false;
    this._heartbeatId = null;
    this._reconnectId = null;
    this._attempt = 0;
    this._queue = [];
    this.serverInfo = null;
    this.currentMode = 'READY';
  }

  connect() {
    this._manualClose = false;
    this.ws = new this.WebSocketImpl(this.url);
    this.ws.addEventListener('open', () => this._onOpen());
    this.ws.addEventListener('message', (event) => this._onMessage(event.data));
    this.ws.addEventListener('close', () => this._onClose());
    this.ws.addEventListener('error', (event) => this._emit('error', { error: event.error || 'WebSocket error' }));
  }

  close() {
    this._manualClose = true;
    this._clearTimers();
    if (this.ws) this.ws.close();
  }

  sendEvent(event, fields = {}) { this._send(buildEvent(this.deviceId, event, fields)); }
  sendState(mode, fields = {}) {
    this.currentMode = mode;
    this._send(buildState(this.deviceId, mode, fields));
  }
  sendAudioChunk(chunk) { this._send(buildAudioChunk(this.deviceId, chunk)); }
  ackCommand(commandId, ok = true) { this._send(buildAck(this.deviceId, commandId, ok)); }

  _onOpen() {
    this._send(buildHello({ deviceId: this.deviceId, deviceName: this.deviceName }));
  }

  _onMessage(raw) {
    let message;
    try { message = parseDatp(raw); }
    catch (error) { this._emit('protocol.error', { error: error.message, raw }); return; }

    if (message.type === 'hello_ack') {
      this.connected = true;
      this._attempt = 0;
      this.serverInfo = message.payload;
      this._startHeartbeat();
      this._flushQueue();
      this._emit('connected', { message });
      return;
    }
    if (message.type === 'command') {
      this._emit('command', { message, ack: (ok = true) => this.ackCommand(message.id, ok) });
      return;
    }
    if (message.type === 'error') {
      this._emit('gateway.error', { message });
      return;
    }
    this._emit('message', { message });
  }

  _onClose() {
    const wasConnected = this.connected;
    this.connected = false;
    this._clearTimers();
    if (wasConnected) this._emit('disconnected', {});
    if (!this._manualClose && this.reconnect) this._scheduleReconnect();
  }

  _send(message) {
    if (!this.ws || this.ws.readyState !== this.WebSocketImpl.OPEN) {
      this._queue.push(message);
      return;
    }
    this.ws.send(JSON.stringify(message));
  }

  _flushQueue() {
    const queue = this._queue.splice(0);
    for (const message of queue) this._send(message);
  }

  _startHeartbeat() {
    if (!this.heartbeatMs) return;
    if (this._heartbeatId) this.timers.clearInterval(this._heartbeatId);
    this._heartbeatId = this.timers.setInterval(() => {
      this.sendEvent('heartbeat', { connected: true });
      this.sendState(this.currentMode, { heartbeat: true });
    }, this.heartbeatMs);
  }

  _scheduleReconnect() {
    const delay = Math.min(1000 * 2 ** this._attempt, 10000);
    this._attempt += 1;
    this._reconnectId = this.timers.setTimeout(() => this.connect(), delay);
  }

  _clearTimers() {
    if (this._heartbeatId) this.timers.clearInterval(this._heartbeatId);
    if (this._reconnectId) this.timers.clearTimeout(this._reconnectId);
    this._heartbeatId = null;
    this._reconnectId = null;
  }

  _emit(type, detail) { this.dispatchEvent(new CustomEvent(type, { detail })); }
}
