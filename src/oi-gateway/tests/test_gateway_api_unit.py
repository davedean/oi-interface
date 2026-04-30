from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from api import GatewayAPI
from character_packs.models import CharacterPack, StateConfig
from registry.models import DeviceInfo
from audio.tts import StubTtsBackend


class DummyRequest:
    def __init__(self, match_info=None, body=None, json_error=False):
        self.match_info = match_info or {}
        self._body = body if body is not None else {}
        self._json_error = json_error

    async def json(self):
        if self._json_error:
            raise json.JSONDecodeError("bad", "x", 0)
        return self._body


def response_json(resp: web.Response):
    return json.loads(resp.text)


@pytest.fixture
def api():
    registry_store = MagicMock()
    registry = SimpleNamespace(
        online_count=2,
        _store=registry_store,
        get_device=AsyncMock(),
        set_character_pack=AsyncMock(return_value=True),
    )
    datp = SimpleNamespace(
        registry=registry,
        device_registry={},
        _server=object(),
        _stopping=False,
    )
    dispatcher = SimpleNamespace(
        show_status=AsyncMock(return_value=True),
        mute_until=AsyncMock(return_value=True),
        audio_play=AsyncMock(return_value=True),
    )
    return GatewayAPI(datp, dispatcher, SimpleNamespace(), tts=None, character_pack_service=None)


@pytest.mark.asyncio
async def test_read_json_invalid(api):
    with pytest.raises(web.HTTPBadRequest):
        await api._read_json(DummyRequest(json_error=True))


@pytest.mark.asyncio
async def test_health_device_info_and_transcript_listing(api):
    now = datetime.now(timezone.utc)
    device = DeviceInfo(
        device_id="dev1",
        device_type="speaker",
        session_id="sess1",
        connected_at=now,
        last_seen=now,
        capabilities={"a": 1},
        resume_token=None,
        nonce=None,
        state={"mode": "READY"},
        audio_cache_bytes=0,
        muted_until=None,
        character_pack_id="robot",
    )
    api._datp.device_registry["dev1"] = {"device_id": "dev1", "session_id": "sess1", "capabilities": {"a": 1}}
    api._datp.registry._store.get_device.return_value = device

    health = response_json(await api._health(DummyRequest()))
    assert health["status"] == "ok"
    assert health["datp_running"] is True
    assert health["devices_online"] == 2

    info = response_json(await api._device_info(DummyRequest(match_info={"device_id": "dev1"})))
    assert info["device_id"] == "dev1"
    assert info["device_type"] == "speaker"
    assert info["state"] == {"mode": "READY"}
    assert info["character_pack_id"] == "robot"

    missing = await api._device_info(DummyRequest(match_info={"device_id": "missing"}))
    assert missing.status == 404

    api._on_event("transcript", "dev1", {"cleaned": "Hello there", "stream_id": "stream-1"})
    api._on_event("agent_response", "dev1", {"response_text": "Hi!", "stream_id": "stream-1", "transcript": "Hello there"})

    transcripts = response_json(await api._transcripts_list(DummyRequest()))
    assert transcripts["count"] == 1
    assert transcripts["transcripts"][0]["device_id"] == "dev1"
    assert transcripts["transcripts"][0]["transcript"] == "Hello there"
    assert transcripts["transcripts"][0]["response"] == "Hi!"
    assert transcripts["transcripts"][0]["conversation_id"] == "stream-1"


@pytest.mark.asyncio
async def test_command_endpoints_validation_and_success(api):
    device_id = "dev1"
    api._datp.device_registry[device_id] = {"device_id": device_id}

    resp = await api._cmd_show_status(DummyRequest(match_info={"device_id": device_id}, body={}))
    assert response_json(resp)["error"] == "Missing required field: state"

    ok = await api._cmd_show_status(DummyRequest(match_info={"device_id": device_id}, body={"state": "thinking", "label": None}))
    assert response_json(ok)["command"] == "display.show_status"
    api._dispatcher.show_status.assert_awaited_once_with(device_id, "thinking", None)

    assert response_json(await api._cmd_mute_until(DummyRequest(match_info={"device_id": device_id}, body={}))) ["error"] == "Missing required field: minutes"
    assert response_json(await api._cmd_mute_until(DummyRequest(match_info={"device_id": device_id}, body={"minutes": "abc"}))) ["error"] == "minutes must be an integer"
    assert response_json(await api._cmd_mute_until(DummyRequest(match_info={"device_id": device_id}, body={"minutes": -1}))) ["error"] == "minutes must be non-negative"

    mute_ok = response_json(await api._cmd_mute_until(DummyRequest(match_info={"device_id": device_id}, body={"minutes": 5})))
    assert mute_ok["command"] == "device.mute_until"
    assert mute_ok["minutes"] == 5

    play_ok = response_json(await api._cmd_audio_play(DummyRequest(match_info={"device_id": device_id}, body={})))
    assert play_ok["response_id"] == "latest"
    api._dispatcher.audio_play.assert_awaited_once_with(device_id, "latest")


@pytest.mark.asyncio
async def test_character_pack_endpoints(api):
    pack = CharacterPack(
        pack_id="robot",
        target="tiny_135x240",
        format="indexed_png",
        states={"idle": StateConfig("idle.png", "Idle")},
    )
    service = SimpleNamespace(list_packs=lambda: [pack], get_pack=lambda pack_id: pack if pack_id == "robot" else None)
    api._pack_service = service

    listed = response_json(await api._character_packs_list(DummyRequest()))
    assert listed["count"] == 1
    assert listed["packs"][0]["pack_id"] == "robot"

    info = response_json(await api._character_pack_info(DummyRequest(match_info={"pack_id": "robot"})))
    assert info["pack_id"] == "robot"

    missing = await api._character_pack_info(DummyRequest(match_info={"pack_id": "missing"}))
    assert missing.status == 404

    api._pack_service = None
    empty = response_json(await api._character_packs_list(DummyRequest()))
    assert empty == {"packs": [], "count": 0}
    missing_service = await api._character_pack_info(DummyRequest(match_info={"pack_id": "robot"}))
    assert missing_service.status == 500


@pytest.mark.asyncio
async def test_set_device_character_paths(api):
    device = DeviceInfo(
        device_id="dev1",
        device_type="speaker",
        session_id="sess1",
        connected_at=None,
        last_seen=None,
        capabilities={},
        resume_token=None,
        nonce=None,
        state={},
        audio_cache_bytes=0,
        muted_until=None,
    )

    req = DummyRequest(match_info={"device_id": "dev1"}, body={})
    assert response_json(await api._set_device_character(req))["error"] == "Missing required field: pack_id"

    api._datp.registry = None
    req = DummyRequest(match_info={"device_id": "dev1"}, body={"pack_id": "robot"})
    assert (await api._set_device_character(req)).status == 500

    registry = SimpleNamespace(get_device=AsyncMock(return_value=None), set_character_pack=AsyncMock(return_value=True))
    api._datp.registry = registry
    assert (await api._set_device_character(req)).status == 404

    registry.get_device.return_value = device
    api._pack_service = SimpleNamespace(get_pack=lambda pack_id: None)
    assert (await api._set_device_character(req)).status == 404

    api._pack_service = SimpleNamespace(get_pack=lambda pack_id: object())
    registry.set_character_pack = AsyncMock(return_value=False)
    assert (await api._set_device_character(req)).status == 500

    registry.set_character_pack = AsyncMock(return_value=True)
    ok = response_json(await api._set_device_character(req))
    assert ok == {"ok": True, "device_id": "dev1", "character_pack_id": "robot"}

    req = DummyRequest(match_info={"device_id": "dev1"}, body={"pack_id": None})
    cleared = response_json(await api._set_device_character(req))
    assert cleared == {"ok": True, "device_id": "dev1", "character_pack_id": None}


@pytest.mark.asyncio
async def test_route_helpers_and_coding_endpoints(api):
    api._tts = StubTtsBackend()
    api._dispatcher.cache_put_begin = AsyncMock(return_value=True)
    api._dispatcher.cache_put_chunk = AsyncMock(return_value=True)
    api._dispatcher.cache_put_end = AsyncMock(return_value=True)

    sent = await api._send_audio_to_device("dev1", "resp1", [b"aa", b"bb"])
    assert sent == {"device_id": "dev1", "response_id": "resp1", "chunks_sent": 2}

    api._dispatcher.cache_put_begin = AsyncMock(return_value=False)
    assert await api._send_audio_to_device("dev1", "resp1", [b"aa"]) is None

    api._dispatcher.cache_put_begin = AsyncMock(return_value=True)
    api._dispatcher.cache_put_chunk = AsyncMock(return_value=False)
    assert await api._send_audio_to_device("dev1", "resp1", [b"aa"]) is None

    api._dispatcher.cache_put_chunk = AsyncMock(return_value=True)
    api._dispatcher.cache_put_end = AsyncMock(return_value=False)
    assert await api._send_audio_to_device("dev1", "resp1", [b"aa"]) is None

    api._dispatcher.cache_put_end = AsyncMock(side_effect=RuntimeError("boom"))
    assert await api._send_audio_to_device("dev1", "resp1", [b"aa"]) is None

    api._dispatcher.cache_put_begin = AsyncMock(return_value=True)
    api._dispatcher.cache_put_chunk = AsyncMock(return_value=True)
    api._dispatcher.cache_put_end = AsyncMock(return_value=True)
    ok = response_json(await api._route_to_devices("hello", ["dev1"], "single", 1.2, False))
    assert ok["ok"] is True
    assert ok["device_ids"] == ["dev1"]

    api._tts = StubTtsBackend()
    api._tts.synthesize = lambda _text: b""
    err = await api._route_to_devices("hello", ["dev1"], "single", 1.2, False)
    assert err.status == 500

    api._tts = StubTtsBackend()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("audio.tts._wav_to_pcm_chunks", lambda wav, size: [])
        err = await api._route_to_devices("hello", ["dev1"], "single", 1.2, False)
        assert err.status == 500

    api._send_audio_to_device = AsyncMock(return_value=None)
    err = await api._route_to_devices("hello", ["dev1"], "single", 1.2, False)
    assert err.status == 500

    coding = SimpleNamespace(
        enabled=True,
        get_status=lambda: {"status": "idle"},
        get_last_result=lambda: {"summary": "ok"},
        enable=MagicMock(),
        disable=MagicMock(),
        clear_history=MagicMock(),
    )
    api._coding_service = None
    assert response_json(await api._coding_status(DummyRequest()))["enabled"] is False
    assert (await api._coding_last_result(DummyRequest())).status == 500
    assert (await api._coding_enable(DummyRequest())).status == 500
    assert (await api._coding_disable(DummyRequest())).status == 500
    assert (await api._coding_clear_history(DummyRequest())).status == 500

    api._coding_service = coding
    assert response_json(await api._coding_status(DummyRequest())) == {"enabled": True, "status": "idle"}
    assert response_json(await api._coding_last_result(DummyRequest())) == {"available": True, "summary": "ok"}
    assert response_json(await api._coding_enable(DummyRequest()))["enabled"] is True
    assert response_json(await api._coding_disable(DummyRequest()))["enabled"] is False
    assert response_json(await api._coding_clear_history(DummyRequest()))["ok"] is True
