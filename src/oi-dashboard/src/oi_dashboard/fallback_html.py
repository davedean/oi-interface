"""Fallback dashboard HTML served when the static UI file is unavailable."""

INLINE_DASHBOARD_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Oi Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: system-ui, sans-serif; margin: 0; padding: 20px; background: #1a1a2e; color: #eee; }
        h1 { color: #00d4ff; margin-bottom: 20px; }
        .container { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; max-width: 1400px; margin: 0 auto; }
        .card { background: #16213e; border-radius: 8px; padding: 16px; }
        .card h2 { color: #00d4ff; margin-top: 0; font-size: 1.1em; }
        .device { display: flex; align-items: center; padding: 12px; margin: 8px 0; background: #0f3460; border-radius: 6px; }
        .status-dot { width: 12px; height: 12px; border-radius: 50%; margin-right: 12px; }
        .online { background: #00ff88; }
        .offline { background: #ff4757; }
        .device-info { flex: 1; }
        .device-name { font-weight: bold; color: #fff; }
        .device-type { color: #888; font-size: 0.85em; }
        .state-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; margin-left: 8px; }
        .transcript { padding: 10px; margin: 6px 0; background: #0f3460; border-radius: 6px; }
        .transcript-time { color: #666; font-size: 0.75em; }
        .transcript-text { color: #fff; margin: 4px 0; }
        .response-text { color: #00d4ff; font-size: 0.9em; margin-top: 4px; }
        .empty { color: #666; font-style: italic; }
        .full-width { grid-column: 1 / -1; }
        @media (max-width: 900px) { .container { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <h1>🖥️ Oi Dashboard</h1>
    <div class="container">
        <div class="card full-width">
            <h2>Gateway Status</h2>
            <div id="gateway-status">Connecting...</div>
        </div>
        <div class="card">
            <h2>📱 Connected Devices</h2>
            <div id="devices-list"><div class="empty">No devices connected</div></div>
        </div>
        <div class="card">
            <h2>🔊 Audio Cache State</h2>
            <div id="audio-cache"><div class="empty">No audio data</div></div>
        </div>
        <div class="card full-width">
            <h2>💬 Recent Transcripts & Responses</h2>
            <div id="transcripts-list"><div class="empty">No transcripts yet</div></div>
        </div>
    </div>
    <script>
        const es = new EventSource('/events');
        let state = { devices: {}, transcripts: [] };

        function formatTime(iso) {
            if (!iso) return '';
            return new Date(iso).toLocaleTimeString();
        }

        function formatBytes(bytes) {
            if (!bytes) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
        }

        function renderDevices() {
            const container = document.getElementById('devices-list');
            const devices = Object.values(state.devices);
            if (devices.length === 0) {
                container.innerHTML = '<div class="empty">No devices connected</div>';
                return;
            }
            container.innerHTML = devices.map(d => `
                <div class="device">
                    <div class="status-dot ${d.online ? 'online' : 'offline'}"></div>
                    <div class="device-info">
                        <div class="device-name">${d.device_id || 'Unknown'}
                            <span class="state-badge" style="background: ${d.online ? '#00ff88' : '#ff4757'}20; color: ${d.online ? '#00ff88' : '#ff4757'}">
                                ${d.online ? 'online' : 'offline'}
                            </span>
                        </div>
                        <div class="device-type">${d.device_type || 'Unknown device'}</div>
                        ${d.state?.mode ? `<div style="color: #888; font-size: 0.85em; margin-top: 4px;">Mode: ${d.state.mode}</div>` : ''}
                    </div>
                </div>
            `).join('');
        }

        function renderAudioCache() {
            const container = document.getElementById('audio-cache');
            const devices = Object.values(state.devices);
            const withCache = devices.filter(d => d.audio_cache_bytes > 0);
            if (withCache.length === 0) {
                container.innerHTML = '<div class="empty">No audio cached</div>';
                return;
            }
            container.innerHTML = withCache.map(d => `
                <div style="padding: 8px 0; border-bottom: 1px solid #0f3460;">
                    <strong>${d.device_id}</strong>: ${formatBytes(d.audio_cache_bytes)}
                </div>
            `).join('');
        }

        function renderTranscripts() {
            const container = document.getElementById('transcripts-list');
            const transcripts = state.transcripts.slice(-10).reverse();
            if (transcripts.length === 0) {
                container.innerHTML = '<div class="empty">No transcripts yet</div>';
                return;
            }
            container.innerHTML = transcripts.map(t => `
                <div class="transcript">
                    <div class="transcript-time">${formatTime(t.timestamp)} — ${t.device_id}</div>
                    <div class="transcript-text">👤 ${t.transcript}</div>
                    ${t.response ? `<div class="response-text">🤖 ${t.response}</div>` : ''}
                </div>
            `).join('');
        }

        function updateGatewayStatus() {
            fetch('/api/health')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('gateway-status').innerHTML = `
                        <span style="color: #00ff88">●</span> Gateway OK — 
                        ${data.devices_online || 0} device(s) online
                    `;
                })
                .catch(() => {
                    document.getElementById('gateway-status').innerHTML = 
                        '<span style="color: #ff4757">●</span> Gateway unreachable';
                });
        }

        es.onmessage = (e) => {
            const msg = JSON.parse(e.data);
            if (msg.type === 'init') {
                state = msg.data;
                renderDevices();
                renderAudioCache();
                renderTranscripts();
            } else if (msg.type === 'device_online' || msg.type === 'device_offline') {
                const d = msg.data;
                if (d.device_id && state.devices[d.device_id]) {
                    state.devices[d.device_id].online = msg.type === 'device_online';
                }
                renderDevices();
            } else if (msg.type === 'transcript') {
                state.transcripts.push({
                    timestamp: msg.data.timestamp,
                    device_id: msg.data.device_id,
                    transcript: msg.data.transcript,
                    response: ''
                });
                renderTranscripts();
            } else if (msg.type === 'agent_response') {
                for (let i = state.transcripts.length - 1; i >= 0; i--) {
                    if (state.transcripts[i].transcript === msg.data.transcript) {
                        state.transcripts[i].response = msg.data.response;
                        break;
                    }
                }
                renderTranscripts();
            } else if (msg.type === 'state_updated') {
                if (state.devices[msg.data.device_id]) {
                    Object.assign(state.devices[msg.data.device_id].state, msg.data.state);
                }
                renderDevices();
            }
        };

        es.onerror = () => {
            document.getElementById('gateway-status').innerHTML = 
                '<span style="color: #ff4757">●</span> SSE disconnected (will reconnect)';
        };

        setInterval(updateGatewayStatus, 5000);
        updateGatewayStatus();
    </script>
</body>
</html>"""
