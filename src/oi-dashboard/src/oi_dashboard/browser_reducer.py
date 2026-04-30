"""Shared browser-side projection reducer for dashboard SSE events."""

DASHBOARD_REDUCER_JS = r"""
function cloneState(currentState) {
    return {
        devices: Object.fromEntries(
            Object.entries(currentState.devices).map(([deviceId, device]) => [
                deviceId,
                {
                    ...device,
                    state: { ...(device.state || {}) },
                    capabilities: { ...(device.capabilities || {}) },
                },
            ]),
        ),
        transcripts: currentState.transcripts.map(entry => ({ ...entry })),
        transcript_limit: currentState.transcript_limit || 100,
    };
}

function applyDevicePatch(deviceMap, deviceId, patch) {
    if (!deviceId) {
        return;
    }
    deviceMap[deviceId] = deviceMap[deviceId] || { device_id: deviceId, state: {}, capabilities: {} };
    const nextDevice = deviceMap[deviceId];
    Object.assign(nextDevice, patch);
    nextDevice.state = nextDevice.state || {};
    nextDevice.capabilities = nextDevice.capabilities || {};
    if (patch.state) {
        Object.assign(nextDevice.state, patch.state);
    }
    if (patch.capabilities) {
        Object.assign(nextDevice.capabilities, patch.capabilities);
    }
}

function upsertTranscript(transcripts, payload, transcriptLimit) {
    const conversationId = payload.conversation_id || '';
    if (!conversationId) {
        return;
    }
    const transcript = {
        ...payload,
        response: payload.response || '',
        stream_id: payload.stream_id || '',
        conversation_id: conversationId,
    };
    const existingIndex = transcripts.findIndex(entry => entry.conversation_id === conversationId);
    if (existingIndex >= 0) {
        transcripts[existingIndex] = { ...transcripts[existingIndex], ...transcript };
    } else {
        transcripts.push(transcript);
    }
    if (transcripts.length > transcriptLimit) {
        transcripts.splice(0, transcripts.length - transcriptLimit);
    }
}

function reduceEvent(currentState, message) {
    const nextState = cloneState(currentState);

    switch (message.type) {
        case 'init':
            return message.data;

        case 'device_online':
            if (message.data.device_id) {
                applyDevicePatch(nextState.devices, message.data.device_id, message.data);
                nextState.devices[message.data.device_id].online = true;
            }
            return nextState;

        case 'device_offline':
            if (message.data.device_id && nextState.devices[message.data.device_id]) {
                nextState.devices[message.data.device_id].online = false;
            }
            return nextState;

        case 'state_updated':
            if (message.data.device_id) {
                applyDevicePatch(nextState.devices, message.data.device_id, { state: message.data.state });
            }
            return nextState;

        case 'transcript':
            upsertTranscript(nextState.transcripts, message.data, nextState.transcript_limit);
            return nextState;

        case 'agent_response':
            upsertTranscript(nextState.transcripts, message.data, nextState.transcript_limit);
            return nextState;

        case 'audio_delivered':
        default:
            return nextState;
    }
}
""".strip()
