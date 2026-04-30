"""Runtime bootstrap for the oi-gateway process."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass

from api import GatewayAPI
from character_packs import CharacterPackService
from audio import (
    AudioDeliveryPipeline,
    StubTtsBackend,
    PiperTtsBackend,
    EspeakNgTtsBackend,
    OpenAiTtsBackend,
    StreamAccumulator,
    FasterWhisperBackend,
    OpenAiWhisperBackend,
    StubSttBackend,
)
from text import TextDeliveryPipeline
from channel import AgentBackend, BackendCatalog, ChannelService, create_backend_catalog_from_env
from channel.factory import BackendProfile
from config_loader import load_gateway_toml_config
from character_packs import CharacterPackStore, CharacterRendererService
from datp import EventBus
from datp.commands import CommandDispatcher
from datp.server import DATPServer
from registry import RegistryService
from registry.store import DeviceStore

logger = logging.getLogger(__name__)


def _load_agent_catalog() -> tuple[dict[str, str] | None, list[dict[str, str]]]:
    raw = os.getenv("OI_AVAILABLE_AGENTS_JSON", "").strip()
    if not raw:
        default_id = os.getenv("OI_DEFAULT_AGENT_ID", "main").strip() or "main"
        label = os.getenv("OI_DEFAULT_AGENT_NAME", default_id).strip() or default_id
        agent = {"id": default_id, "name": label}
        return agent, [agent]

    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise ValueError("OI_AVAILABLE_AGENTS_JSON must be a non-empty JSON array")
    agents: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id") or item.get("name") or "").strip()
        if not agent_id:
            continue
        agents.append({"id": agent_id, "name": str(item.get("name") or agent_id)})
    if not agents:
        raise ValueError("OI_AVAILABLE_AGENTS_JSON contained no usable agents")
    default_id = str(os.getenv("OI_DEFAULT_AGENT_ID") or agents[0]["id"])
    default_agent = next((agent for agent in agents if agent["id"] == default_id), agents[0])
    return default_agent, agents


def _build_tts_backend() -> object:
    """Select TTS backend from env, defaulting to OpenAI when available.

    OI_TTS_BACKEND values:
    - openai (default)
    - piper
    - espeak-ng
    - stub
    """
    backend = os.getenv("OI_TTS_BACKEND", "openai").strip().lower()
    if backend == "stub":
        logger.warning("Using StubTtsBackend (silent test audio)")
        return StubTtsBackend()
    if backend == "espeak-ng":
        try:
            voice = os.getenv("OI_TTS_VOICE", "en")
            tts = EspeakNgTtsBackend(voice=voice)
            logger.info("Using EspeakNgTtsBackend voice=%s", voice)
            return tts
        except Exception as exc:
            logger.warning("espeak-ng TTS unavailable (%s); falling back to StubTtsBackend", exc)
            return StubTtsBackend()
    if backend == "openai":
        try:
            api_key = os.getenv("OPENAI_API_KEY", "")
            model = os.getenv("OI_OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
            voice = os.getenv("OI_OPENAI_TTS_VOICE", "alloy")
            tts = OpenAiTtsBackend(api_key=api_key, model=model, voice=voice)
            logger.info("Using OpenAiTtsBackend model=%s voice=%s", model, voice)
            return tts
        except Exception as exc:
            logger.warning("OpenAI TTS unavailable (%s); falling back to StubTtsBackend", exc)
            return StubTtsBackend()

    try:
        voice = os.getenv("OI_TTS_VOICE", "en_US-lessac-medium")
        model_path = os.getenv("OI_PIPER_MODEL_PATH")
        tts = PiperTtsBackend(voice=voice, model_path=model_path)
        logger.info("Using PiperTtsBackend voice=%s model_path=%s", voice, model_path or "<auto>")
        return tts
    except Exception as exc:
        logger.warning("Piper TTS unavailable (%s); falling back to StubTtsBackend", exc)
        return StubTtsBackend()


def _build_stt_backend() -> object:
    """Select STT backend from env, defaulting to faster-whisper when available.

    OI_STT_BACKEND values:
    - whisper (default, faster-whisper local)
    - openai
    - stub
    """
    backend = os.getenv("OI_STT_BACKEND", "whisper").strip().lower()
    if backend == "stub":
        logger.warning("Using StubSttBackend")
        return StubSttBackend()
    if backend == "openai":
        try:
            api_key = os.getenv("OPENAI_API_KEY", "")
            model = os.getenv("OI_OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")
            stt = OpenAiWhisperBackend(api_key=api_key, model=model)
            logger.info("Using OpenAiWhisperBackend model=%s", model)
            return stt
        except Exception as exc:
            logger.warning("OpenAI STT unavailable (%s); falling back to StubSttBackend", exc)
            return StubSttBackend()

    try:
        model = os.getenv("OI_STT_MODEL", "base.en")
        device = os.getenv("OI_STT_DEVICE", "cpu")
        compute_type = os.getenv("OI_STT_COMPUTE_TYPE", "int8")
        stt = FasterWhisperBackend(model=model, device=device, compute_type=compute_type)
        logger.info("Using FasterWhisperBackend model=%s device=%s compute_type=%s", model, device, compute_type)
        return stt
    except Exception as exc:
        logger.warning("Whisper STT unavailable (%s); falling back to StubSttBackend", exc)
        return StubSttBackend()


@dataclass
class GatewayRuntime:
    """Owns the running gateway components and their lifecycle."""

    agent_backend: AgentBackend
    backend_catalog: BackendCatalog | None = None
    default_agent: dict[str, str] | None = None
    available_agents: list[dict[str, str]] | None = None
    datp_host: str = "0.0.0.0"
    datp_port: int = 8787
    api_host: str = "0.0.0.0"
    api_port: int = 8788
    tts: object | None = None

    def __post_init__(self) -> None:
        self.tts = self.tts or _build_tts_backend()
        self.event_bus = EventBus()
        self.store = DeviceStore()
        self.registry = RegistryService(store=self.store, event_bus=self.event_bus)
        catalog = self.backend_catalog
        if catalog is None:
            catalog = BackendCatalog(
                [BackendProfile(id=getattr(self.agent_backend, "name", "pi"), label=str(getattr(self.agent_backend, "name", "pi")).title(), backend=self.agent_backend)],
                default_backend_id=str(getattr(self.agent_backend, "name", "pi")),
            )
            self.backend_catalog = catalog

        self.server = DATPServer(
            host=self.datp_host,
            port=self.datp_port,
            event_bus=self.event_bus,
            registry=self.registry,
            available_backends=catalog.available_backends(),
            default_backend_id=catalog.default_backend_id,
            default_agent=self.default_agent,
            available_agents=self.available_agents or [],
        )
        self.dispatcher = CommandDispatcher(self.server)
        self.channel_service = ChannelService(
            event_bus=self.event_bus,
            registry=self.registry,
            pi_backend=self.agent_backend,
            command_dispatcher=self.dispatcher,
            backend_catalog=self.backend_catalog,
            conversation_resolver=self.server.get_device_conversation,
        )
        self.audio_delivery = AudioDeliveryPipeline(
            event_bus=self.event_bus,
            dispatcher=self.dispatcher,
            tts=self.tts,
        )
        self.stt = _build_stt_backend()
        self.stream_accumulator = StreamAccumulator(
            event_bus=self.event_bus,
            stt=self.stt,
        )
        self.text_delivery = TextDeliveryPipeline(
            event_bus=self.event_bus,
            dispatcher=self.dispatcher,
        )
        logger.info(""""
============
OI GATEWAY STARTED
TextDeliveryPipeline ENABLED
Streaming support: ACTIVE
============
""")
        # Character pack store and renderer
        self.pack_store = CharacterPackStore()
        self.pack_service = CharacterPackService(self.pack_store)
        self.character_renderer = CharacterRendererService(
            server=self.server,
            registry=self.registry,
            command_dispatcher=self.dispatcher,
        )
        self.dispatcher.set_character_renderer(self.character_renderer)
        self.api = GatewayAPI(
            datp_server=self.server,
            command_dispatcher=self.dispatcher,
            event_bus=self.event_bus,
            host=self.api_host,
            port=self.api_port,
            tts=self.tts,
            character_pack_service=self.pack_service,
        )

    async def start(self) -> None:
        await self.server.start()
        await self.api.start()
        logger.info(
            "Gateway runtime started",
            extra={
                "datp_host": self.server.host,
                "datp_port": self.server.port,
                "api_host": self.api._host,
                "api_port": self.api._port,
                "backend_mode": getattr(self.agent_backend, "mode", type(self.agent_backend).__name__),
            },
        )

    async def stop(self) -> None:
        await self.api.stop()
        await self.server.stop()
        self.store.close()
        logger.info("Gateway runtime stopped")


async def run_forever(runtime: GatewayRuntime) -> None:
    """Start the runtime and keep it alive until cancelled."""
    await runtime.start()
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        await runtime.stop()


async def main() -> None:
    """TOML + environment configured gateway bootstrap."""
    load_gateway_toml_config()
    logger.info("Gateway python executable: %s", sys.executable)
    logger.info("Gateway python version: %s", sys.version.split()[0])
    logger.info("OI_AGENT_BACKEND=%s OI_TTS_BACKEND=%s", os.getenv("OI_AGENT_BACKEND", "pi"), os.getenv("OI_TTS_BACKEND", "openai"))
    catalog = create_backend_catalog_from_env()
    default_backend = catalog.get(catalog.default_backend_id)
    default_agent, available_agents = _load_agent_catalog()
    runtime = GatewayRuntime(
        agent_backend=default_backend,
        backend_catalog=catalog,
        default_agent=default_agent,
        available_agents=available_agents,
        datp_host=os.getenv("OI_GATEWAY_HOST", "0.0.0.0"),
        datp_port=int(os.getenv("OI_GATEWAY_PORT", "8787")),
        api_host=os.getenv("OI_GATEWAY_API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("OI_GATEWAY_API_PORT", "8788")),
    )
    await run_forever(runtime)


if __name__ == "__main__":
    asyncio.run(main())
