"""OpenClaw agent backend via direct Gateway WebSocket RPC."""
from __future__ import annotations

import asyncio
import json
import itertools
import logging
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, AsyncGenerator

import aiohttp

from .backend import AgentBackend, AgentBackendError, AgentRequest, AgentResponse, AgentStreamChunk
from .request_builder import render_text_prompt
from runtime_paths import openclaw_device_identity_path

logger = logging.getLogger(__name__)


class OpenClawBackend(AgentBackend):
    """Send requests to a running OpenClaw Gateway over WebSocket RPC."""

    mode = "openclaw"

    def __init__(
        self,
        *,
        url: str,
        token: str,
        timeout_seconds: float = 120.0,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._url = url
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._session_factory = session_factory or aiohttp.ClientSession
        self._id_counter = itertools.count(1)
        self._device_identity: dict[str, str] | None = None

    @property
    def name(self) -> str:
        return "openclaw"

    async def send_request_streaming(self, request: AgentRequest) -> AsyncGenerator[AgentStreamChunk, None]:
        """Send a request and stream response chunks from OpenClaw."""
        async with self._session_factory() as session:
            async with session.ws_connect(self._url, heartbeat=30.0) as ws:
                await self._perform_connect_handshake(ws)

                request_id = self._next_id("agent")
                session_key = self._map_session_key(request.session_key, request.source_device_id)
                await ws.send_json(self._build_agent_request(request_id, request, session_key))

                streamed_text = ""
                while True:
                    frame = await self._receive_json(ws)
                    event_chunk = self._build_event_chunk(frame, streamed_text)
                    if event_chunk is not None:
                        streamed_text += event_chunk.text_delta
                        yield event_chunk
                        continue

                    is_complete, final_chunk = self._handle_response_frame(frame, request_id, streamed_text)
                    if not is_complete:
                        continue
                    if final_chunk is not None:
                        yield final_chunk
                    break

    async def send_request(self, request: AgentRequest) -> AgentResponse:
        """Send a request and accumulate streaming chunks."""
        last_text = ""
        metadata = {}
        async for chunk in self.send_request_streaming(request):
            if chunk.text_delta:
                last_text = chunk.text_delta if chunk.is_final else last_text + chunk.text_delta
            if chunk.metadata:
                metadata.update(chunk.metadata)

        if not last_text:
            raise AgentBackendError("OpenClaw backend returned no assistant text")

        return AgentResponse(
            response_text=last_text,
            backend_name=self.name,
            session_key=self._map_session_key(request.session_key, request.source_device_id),
            correlation_id=request.correlation_id,
            raw_response={},
            metadata=metadata,
        )

    async def _build_connect_request(self, request_id: str, nonce: str) -> dict[str, Any]:
        device_identity = self._load_or_create_device_identity()
        signed_at_ms = int(time.time() * 1000)
        client_id = "gateway-client"
        client_mode = "backend"
        signature_payload = self._build_device_auth_payload_v3(
            device_id=device_identity["deviceId"],
            client_id=client_id,
            client_mode=client_mode,
            role="operator",
            scopes=["operator.read", "operator.write"],
            signed_at_ms=signed_at_ms,
            token=self._token,
            nonce=nonce,
            platform="linux",
            device_family=None,
        )
        signature = self._sign_device_payload(device_identity["privateKeyPem"], signature_payload)
        return {
            "type": "req",
            "id": request_id,
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": client_id,
                    "version": "oi-gateway",
                    "platform": "linux",
                    "mode": client_mode,
                },
                "role": "operator",
                "scopes": ["operator.read", "operator.write"],
                "caps": [],
                "commands": [],
                "permissions": {},
                "auth": {"token": self._token},
                "locale": "en-US",
                "userAgent": "oi-gateway/openclaw-backend",
                "device": {
                    "id": device_identity["deviceId"],
                    "publicKey": device_identity["publicKeyRawBase64Url"],
                    "signature": signature,
                    "signedAt": signed_at_ms,
                    "nonce": nonce,
                },
            },
        }

    def _build_agent_request(
        self,
        request_id: str,
        request: AgentRequest,
        session_key: str,
    ) -> dict[str, Any]:
        return {
            "type": "req",
            "id": request_id,
            "method": "agent",
            "params": {
                "message": render_text_prompt(request),
                "sessionKey": session_key,
                "idempotencyKey": request.idempotency_key or request.correlation_id or request.user_text,
            },
        }

    def _assert_ok_response(self, frame: dict[str, Any], expected_id: str, context: str) -> None:
        self._assert_matching_response(frame, expected_id)
        if frame.get("ok") is not True:
            error = frame.get("error") or {}
            if isinstance(error, dict):
                raise AgentBackendError(f"{context} failed: {error.get('message', 'unknown error')}")
            raise AgentBackendError(f"{context} failed")

    def _log_hello_ok(self, frame: dict[str, Any]) -> None:
        payload = frame.get("payload")
        if not isinstance(payload, dict):
            return
        auth = payload.get("auth")
        if not isinstance(auth, dict):
            return
        role = auth.get("role")
        scopes = auth.get("scopes")
        server = payload.get("server")
        server_version = None
        conn_id = None
        if isinstance(server, dict):
            server_version = server.get("version")
            conn_id = server.get("connId")
        logger.info(
            "OpenClaw hello-ok auth role=%s scopes=%s server_version=%s conn_id=%s",
            role,
            scopes,
            server_version,
            conn_id,
        )

    def _log_connect_request(self, request: dict[str, Any]) -> None:
        params = request.get("params")
        if not isinstance(params, dict):
            return
        client = params.get("client") if isinstance(params.get("client"), dict) else {}
        auth = params.get("auth")
        device = params.get("device")
        logger.info(
            "OpenClaw connect request client=%s mode=%s role=%s scopes=%s auth_token=%s device=%s",
            client.get("id"),
            client.get("mode"),
            params.get("role"),
            params.get("scopes"),
            bool(auth.get("token")) if isinstance(auth, dict) else False,
            bool(device),
        )

    def _load_or_create_device_identity(self) -> dict[str, str]:
        if self._device_identity is not None:
            return self._device_identity
        identity_path = self._device_identity_path()
        identity_path.parent.mkdir(parents=True, exist_ok=True)
        identity = self._node_load_or_create_device_identity(identity_path)
        self._device_identity = identity
        return identity

    def _device_identity_path(self) -> Path:
        return openclaw_device_identity_path()

    def _legacy_device_identity_path(self) -> Path:
        return Path.cwd() / ".run" / "openclaw-device-identity.json"

    def _node_load_or_create_device_identity(self, identity_path: Path) -> dict[str, str]:
        script = r"""
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const identityPath = process.argv[1];
const legacyIdentityPath = process.argv[2];
const ED25519_SPKI_PREFIX = Buffer.from("302a300506032b6570032100", "hex");

function base64UrlEncode(buf) {
  return Buffer.from(buf).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function derivePublicKeyRaw(publicKeyPem) {
  const key = crypto.createPublicKey(publicKeyPem);
  const spki = key.export({ type: "spki", format: "der" });
  if (
    spki.length === ED25519_SPKI_PREFIX.length + 32 &&
    spki.subarray(0, ED25519_SPKI_PREFIX.length).equals(ED25519_SPKI_PREFIX)
  ) {
    return spki.subarray(ED25519_SPKI_PREFIX.length);
  }
  return spki;
}

function fingerprintPublicKey(publicKeyPem) {
  const raw = derivePublicKeyRaw(publicKeyPem);
  return crypto.createHash("sha256").update(raw).digest("hex");
}

function normalizeStored(raw) {
  if (!raw || raw.version !== 1) {
    return null;
  }
  if (
    typeof raw.deviceId !== "string" ||
    typeof raw.publicKeyPem !== "string" ||
    typeof raw.privateKeyPem !== "string" ||
    typeof raw.publicKeyRawBase64Url !== "string"
  ) {
    return null;
  }
  const derivedId = fingerprintPublicKey(raw.publicKeyPem);
  if (!derivedId || derivedId !== raw.deviceId) {
    return null;
  }
  return {
    deviceId: raw.deviceId,
    publicKeyPem: raw.publicKeyPem,
    privateKeyPem: raw.privateKeyPem,
    publicKeyRawBase64Url: raw.publicKeyRawBase64Url,
  };
}

function loadStoredIdentity(candidatePath) {
  try {
    if (candidatePath && fs.existsSync(candidatePath)) {
      const existing = normalizeStored(JSON.parse(fs.readFileSync(candidatePath, "utf8")));
      if (existing) {
        return { identity: existing, sourcePath: candidatePath };
      }
    }
  } catch {}
  return null;
}

try {
  const existing = loadStoredIdentity(identityPath) || loadStoredIdentity(legacyIdentityPath);
  if (existing) {
    if (existing.sourcePath !== identityPath) {
      fs.mkdirSync(path.dirname(identityPath), { recursive: true });
      const migrated = {
        version: 1,
        deviceId: existing.identity.deviceId,
        publicKeyPem: existing.identity.publicKeyPem,
        privateKeyPem: existing.identity.privateKeyPem,
        publicKeyRawBase64Url: existing.identity.publicKeyRawBase64Url,
        createdAtMs: Date.now(),
      };
      fs.writeFileSync(identityPath, `${JSON.stringify(migrated, null, 2)}\n`, { mode: 0o600 });
      try {
        fs.chmodSync(identityPath, 0o600);
      } catch {}
    }
    process.stdout.write(JSON.stringify(existing.identity));
    process.exit(0);
  }
} catch {}

const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
const publicKeyPem = publicKey.export({ type: "spki", format: "pem" }).toString();
const privateKeyPem = privateKey.export({ type: "pkcs8", format: "pem" }).toString();
const publicKeyRawBase64Url = base64UrlEncode(derivePublicKeyRaw(publicKeyPem));
const deviceId = fingerprintPublicKey(publicKeyPem);
const stored = {
  version: 1,
  deviceId,
  publicKeyPem,
  privateKeyPem,
  publicKeyRawBase64Url,
  createdAtMs: Date.now(),
};
fs.mkdirSync(path.dirname(identityPath), { recursive: true });
fs.writeFileSync(identityPath, `${JSON.stringify(stored, null, 2)}\n`, { mode: 0o600 });
try {
  fs.chmodSync(identityPath, 0o600);
} catch {}
process.stdout.write(JSON.stringify({
  deviceId,
  publicKeyPem,
  privateKeyPem,
  publicKeyRawBase64Url,
}));
"""
        proc = subprocess.run(
            ["node", "-e", script, str(identity_path), str(self._legacy_device_identity_path())],
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(proc.stdout)
        if not all(
            isinstance(data.get(field), str)
            for field in ("deviceId", "publicKeyPem", "privateKeyPem", "publicKeyRawBase64Url")
        ):
            raise AgentBackendError("OpenClaw backend device identity helper returned malformed data")
        return {
            "deviceId": str(data["deviceId"]),
            "publicKeyPem": str(data["publicKeyPem"]),
            "privateKeyPem": str(data["privateKeyPem"]),
            "publicKeyRawBase64Url": str(data["publicKeyRawBase64Url"]),
        }

    def _sign_device_payload(self, private_key_pem: str, payload: str) -> str:
        script = r"""
const crypto = require("node:crypto");
const fs = require("node:fs");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const key = crypto.createPrivateKey(input.privateKeyPem);
const sig = crypto.sign(null, Buffer.from(input.payload, "utf8"), key);
process.stdout.write(Buffer.from(sig).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, ""));
"""
        proc = subprocess.run(
            ["node", "-e", script],
            input=json.dumps({"privateKeyPem": private_key_pem, "payload": payload}),
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()

    def _build_device_auth_payload_v3(
        self,
        *,
        device_id: str,
        client_id: str,
        client_mode: str,
        role: str,
        scopes: list[str],
        signed_at_ms: int,
        token: str,
        nonce: str,
        platform: str | None,
        device_family: str | None,
    ) -> str:
        def normalize(value: str | None) -> str:
            return (value or "").strip().lower()

        return "|".join(
            [
                "v3",
                device_id,
                client_id,
                client_mode,
                role,
                ",".join(scopes),
                str(signed_at_ms),
                token or "",
                nonce,
                normalize(platform),
                normalize(device_family),
            ]
        )

    def _assert_matching_response(self, frame: dict[str, Any], expected_id: str) -> None:
        if frame.get("type") != "res":
            raise AgentBackendError("OpenClaw backend received unexpected non-response frame")
        if frame.get("id") != expected_id:
            raise AgentBackendError("OpenClaw backend received mismatched response id")
        if frame.get("ok") is not True:
            error = frame.get("error") or {}
            if isinstance(error, dict):
                raise AgentBackendError(error.get("message", "OpenClaw request failed"))
            raise AgentBackendError("OpenClaw request failed")

    def map_session_key(self, request: AgentRequest) -> str:
        return self._map_session_key(request.session_key, request.source_device_id)

    def _map_session_key(self, session_key: str | None, source_device_id: str) -> str:
        if session_key and session_key.startswith("agent:"):
            return session_key
        suffix = source_device_id
        if session_key and session_key.startswith("oi:device:"):
            suffix = session_key.removeprefix("oi:device:")
        return f"agent:main:oi:device:{suffix}"

    async def _perform_connect_handshake(self, ws: Any) -> None:
        challenge = await self._receive_json(ws)
        nonce = self._extract_connect_nonce(challenge)

        connect_id = self._next_id("connect")
        connect_request = await self._build_connect_request(connect_id, nonce)
        self._log_connect_request(connect_request)
        await ws.send_json(connect_request)

        hello = await self._receive_json(ws)
        self._assert_ok_response(hello, connect_id, "OpenClaw connect")
        self._log_hello_ok(hello)

    async def _receive_json(self, ws: Any) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(ws.receive_json(), timeout=self._timeout_seconds)
        except TimeoutError as exc:
            raise AgentBackendError(
                f"OpenClaw backend timed out waiting for gateway response after {self._timeout_seconds:.1f}s"
            ) from exc

    def _extract_connect_nonce(self, challenge: dict[str, Any]) -> str:
        if challenge.get("type") != "event" or challenge.get("event") != "connect.challenge":
            raise AgentBackendError("OpenClaw gateway did not send connect.challenge")
        payload = challenge.get("payload") if isinstance(challenge.get("payload"), dict) else {}
        nonce = str(payload.get("nonce") or "").strip()
        if not nonce:
            raise AgentBackendError("OpenClaw gateway connect.challenge missing nonce")
        return nonce

    def _build_event_chunk(self, frame: dict[str, Any], streamed_text: str = "") -> AgentStreamChunk | None:
        if frame.get("type") != "event":
            return None
        event_name = frame.get("event")
        payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
        text = self._extract_text_from_openclaw_payload(payload)
        if not text:
            return None
        delta = self._remaining_response_text(streamed_text, text)
        if not delta:
            return None
        logger.debug("OpenClaw streaming text: %s", delta[:50])
        return AgentStreamChunk(text_delta=delta, is_final=False, metadata={"event": event_name})

    def _handle_response_frame(
        self,
        frame: dict[str, Any],
        request_id: str,
        streamed_text: str,
    ) -> tuple[bool, AgentStreamChunk | None]:
        self._assert_matching_response(frame, request_id)
        payload = frame.get("payload")
        if not isinstance(payload, dict):
            raise AgentBackendError("OpenClaw backend returned malformed payload")
        if payload.get("status") == "accepted":
            return False, None

        response_text = self._extract_response_text(payload)
        if not response_text:
            raise AgentBackendError("OpenClaw backend returned no assistant text")

        remaining_text = self._remaining_response_text(streamed_text, response_text)
        if not remaining_text:
            return True, None
        return True, AgentStreamChunk(
            text_delta=remaining_text,
            is_final=True,
            metadata=self._extract_metadata(payload),
        )

    def _remaining_response_text(self, streamed_text: str, response_text: str) -> str:
        if not streamed_text:
            return response_text
        if response_text == streamed_text:
            return ""
        if response_text.startswith(streamed_text):
            return response_text[len(streamed_text):]
        return response_text

    def _extract_text_from_openclaw_payload(self, payload: dict[str, Any]) -> str:
        """Extract text from OpenClaw event payload."""
        if not isinstance(payload, dict):
            return ""
        for key in ("text", "content", "message", "delta", "data"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    def _extract_response_text(self, payload: dict[str, Any]) -> str | None:
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        payloads = result.get("payloads")
        if not isinstance(payloads, list):
            return None
        texts: list[str] = []
        for item in payloads:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
        if texts:
            return "\n".join(texts)
        return None

    def _extract_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = payload.get("result")
        if not isinstance(result, dict):
            return {}
        meta = result.get("meta")
        return meta if isinstance(meta, dict) else {}

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._id_counter)}"
