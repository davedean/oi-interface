from __future__ import annotations

from pathlib import Path
import sys

import pytest


gateway_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(gateway_src))

from channel.backend import AgentBackendError, AgentRequest
from channel.openclaw_backend import OpenClawBackend


class FakeWebSocket:
    def __init__(self, messages: list[dict]) -> None:
        self._messages = list(messages)
        self.sent: list[dict] = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True
        return None

    async def receive_json(self):
        if not self._messages:
            raise RuntimeError("no more websocket messages")
        return self._messages.pop(0)

    async def send_json(self, payload: dict):
        self.sent.append(payload)


class FakeSession:
    def __init__(self, ws: FakeWebSocket) -> None:
        self.ws = ws
        self.ws_connect_calls: list[dict] = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True
        return None

    def ws_connect(self, url: str, *, heartbeat: float | None = None):
        self.ws_connect_calls.append({"url": url, "heartbeat": heartbeat})
        return self.ws


def make_request() -> AgentRequest:
    return AgentRequest(
        user_text="mute for 30 minutes.",
        source_device_id="test-device",
        input_kind="transcript",
        stream_id="rec_001",
        transcript="mute for 30 minutes.",
        session_key="oi:device:test-device",
        correlation_id="rec_001",
        idempotency_key="idem-001",
        device_context={
            "source_device": "test-device",
            "foreground": "test-device",
            "online": ["test-device"],
            "capabilities": {"test-device": {"max_spoken_seconds": 12, "supports_confirm_buttons": True}},
        },
        reply_constraints={"max_spoken_seconds": 12, "supports_confirm_buttons": True},
    )


def make_backend(ws: FakeWebSocket, *, token: str = "secret-token") -> tuple[OpenClawBackend, FakeSession]:
    session = FakeSession(ws)
    backend = OpenClawBackend(
        url="ws://127.0.0.1:18789",
        token=token,
        session_factory=lambda: session,
    )
    backend._load_or_create_device_identity = lambda: {
        "deviceId": "device-1",
        "publicKeyPem": "-----BEGIN PUBLIC KEY-----\nMIIB...\n-----END PUBLIC KEY-----\n",
        "privateKeyPem": "-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----\n",
        "publicKeyRawBase64Url": "pub-key-raw",
    }
    backend._sign_device_payload = lambda private_key_pem, payload: "signature-1"
    return backend, session


@pytest.mark.asyncio
async def test_openclaw_backend_connects_and_waits_for_final_agent_response():
    ws = FakeWebSocket(
        [
            {"type": "event", "event": "connect.challenge", "payload": {"nonce": "nonce-1", "ts": 1}},
            {
                "type": "res",
                "id": "connect-1",
                "ok": True,
                "payload": {
                    "type": "hello-ok",
                    "protocol": 3,
                    "server": {"version": "test", "connId": "conn-1"},
                    "features": {"methods": ["agent"], "events": []},
                    "snapshot": {},
                    "auth": {"role": "operator", "scopes": ["operator.admin", "operator.read", "operator.write"]},
                    "policy": {"maxPayload": 26214400, "maxBufferedBytes": 52428800, "tickIntervalMs": 15000},
                },
            },
            {"type": "res", "id": "agent-2", "ok": True, "payload": {"runId": "run-1", "status": "accepted"}},
            {
                "type": "res",
                "id": "agent-2",
                "ok": True,
                "payload": {
                    "runId": "run-1",
                    "status": "ok",
                    "result": {
                        "payloads": [{"text": "Muted for 30 minutes."}],
                        "meta": {"agentMeta": {"provider": "test", "model": "test-model"}},
                    },
                },
            },
        ]
    )
    backend, session = make_backend(ws)

    result = await backend.send_request(make_request())

    assert result.response_text == "Muted for 30 minutes."
    assert result.backend_name == "openclaw"
    assert result.session_key == "agent:main:oi:device:test-device"
    assert result.correlation_id == "rec_001"

    assert session.ws_connect_calls == [{"url": "ws://127.0.0.1:18789", "heartbeat": 30.0}]
    assert len(ws.sent) == 2

    connect = ws.sent[0]
    assert connect["type"] == "req"
    assert connect["method"] == "connect"
    assert connect["params"]["auth"] == {"token": "secret-token"}
    assert connect["params"]["client"]["id"] == "gateway-client"
    assert connect["params"]["client"]["mode"] == "backend"
    assert connect["params"]["scopes"] == ["operator.read", "operator.write"]
    assert connect["params"]["commands"] == []
    assert connect["params"]["permissions"] == {}
    device = connect["params"]["device"]
    assert device["id"] == "device-1"
    assert device["publicKey"] == "pub-key-raw"
    assert device["signature"] == "signature-1"
    assert device["nonce"] == "nonce-1"
    assert isinstance(device["signedAt"], int)

    agent = ws.sent[1]
    assert agent["type"] == "req"
    assert agent["method"] == "agent"
    params = agent["params"]
    assert params["sessionKey"] == "agent:main:oi:device:test-device"
    assert params["idempotencyKey"] == "idem-001"
    assert params["message"].startswith("The user said: 'mute for 30 minutes.'")


@pytest.mark.asyncio
async def test_openclaw_backend_raises_on_gateway_error_response():
    ws = FakeWebSocket(
        [
            {"type": "event", "event": "connect.challenge", "payload": {"nonce": "nonce-1", "ts": 1}},
            {
                "type": "res",
                "id": "connect-1",
                "ok": True,
                "payload": {
                    "type": "hello-ok",
                    "protocol": 3,
                    "server": {"version": "test", "connId": "conn-1"},
                    "features": {"methods": ["agent"], "events": []},
                    "snapshot": {},
                    "auth": {"role": "operator", "scopes": ["operator.admin", "operator.read", "operator.write"]},
                    "policy": {"maxPayload": 26214400, "maxBufferedBytes": 52428800, "tickIntervalMs": 15000},
                },
            },
            {"type": "res", "id": "agent-2", "ok": False, "error": {"message": "missing scope"}},
        ]
    )
    backend, _session = make_backend(ws)

    with pytest.raises(AgentBackendError, match="missing scope"):
        await backend.send_request(make_request())


@pytest.mark.asyncio
async def test_openclaw_backend_raises_when_no_connect_challenge_arrives():
    ws = FakeWebSocket([{"type": "event", "event": "other.event", "payload": {}}])
    backend, _session = make_backend(ws)

    with pytest.raises(AgentBackendError, match="connect.challenge"):
        await backend.send_request(make_request())


@pytest.mark.asyncio
async def test_openclaw_backend_raises_when_no_text_payload_present():
    ws = FakeWebSocket(
        [
            {"type": "event", "event": "connect.challenge", "payload": {"nonce": "nonce-1", "ts": 1}},
            {
                "type": "res",
                "id": "connect-1",
                "ok": True,
                "payload": {
                    "type": "hello-ok",
                    "protocol": 3,
                    "server": {"version": "test", "connId": "conn-1"},
                    "features": {"methods": ["agent"], "events": []},
                    "snapshot": {},
                    "auth": {"role": "operator", "scopes": ["operator.admin", "operator.read", "operator.write"]},
                    "policy": {"maxPayload": 26214400, "maxBufferedBytes": 52428800, "tickIntervalMs": 15000},
                },
            },
            {"type": "res", "id": "agent-2", "ok": True, "payload": {"runId": "run-1", "status": "accepted"}},
            {"type": "res", "id": "agent-2", "ok": True, "payload": {"runId": "run-1", "status": "ok", "result": {"payloads": []}}},
        ]
    )
    backend, _session = make_backend(ws)

    with pytest.raises(AgentBackendError, match="assistant text"):
        await backend.send_request(make_request())


def test_openclaw_backend_device_identity_path_uses_oi_home(tmp_path, monkeypatch):
    monkeypatch.setenv("OI_HOME", str(tmp_path / "oi-home"))
    backend, _session = make_backend(FakeWebSocket([]))

    assert backend._device_identity_path() == (
        tmp_path / "oi-home" / "state" / "oi-gateway" / "openclaw-device-identity.json"
    )
