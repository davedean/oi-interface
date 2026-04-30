"""Runtime bootstrap for the oi-gateway process."""
from __future__ import annotations

import asyncio
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
    StreamAccumulator,
    FasterWhisperBackend,
    StubSttBackend,
)
from text import TextDeliveryPipeline
from channel import AgentBackend, ChannelService, create_backend_from_env
from character_packs import CharacterPackStore, CharacterRendererService
from datp import EventBus
from datp.commands import CommandDispatcher
from datp.server import DATPServer
from registry import RegistryService
from registry.store import DeviceStore

logger = logging.getLogger(__name__)


def _build_tts_backend() -> object:
    """Select TTS backend from env, defaulting to Piper when available.

    OI_TTS_BACKEND values:
    - piper (default)
    - stub
    """
    backend = os.getenv("OI_TTS_BACKEND", "piper").strip().lower()
    if backend == "stub":
        logger.warning("Using StubTtsBackend (silent test audio)")
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
    - whisper (default)
    - stub
    """
    backend = os.getenv("OI_STT_BACKEND", "whisper").strip().lower()
    if backend == "stub":
        logger.warning("Using StubSttBackend")
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
        self.server = DATPServer(
            host=self.datp_host,
            port=self.datp_port,
            event_bus=self.event_bus,
            registry=self.registry,
        )
        self.dispatcher = CommandDispatcher(self.server)
        self.channel_service = ChannelService(
            event_bus=self.event_bus,
            registry=self.registry,
            pi_backend=self.agent_backend,
            command_dispatcher=self.dispatcher,
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
    """Environment-configured gateway bootstrap."""
    logger.info("Gateway python executable: %s", sys.executable)
    logger.info("Gateway python version: %s", sys.version.split()[0])
    logger.info("OI_AGENT_BACKEND=%s OI_TTS_BACKEND=%s", os.getenv("OI_AGENT_BACKEND", "pi"), os.getenv("OI_TTS_BACKEND", "piper"))
    backend = create_backend_from_env()
    runtime = GatewayRuntime(
        agent_backend=backend,
        datp_host=os.getenv("OI_GATEWAY_HOST", "0.0.0.0"),
        datp_port=int(os.getenv("OI_GATEWAY_PORT", "8787")),
        api_host=os.getenv("OI_GATEWAY_API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("OI_GATEWAY_API_PORT", "8788")),
    )
    await run_forever(runtime)


if __name__ == "__main__":
    asyncio.run(main())
