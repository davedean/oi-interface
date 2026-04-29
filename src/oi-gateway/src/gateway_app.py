"""Runtime bootstrap for the oi-gateway process."""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

from api import GatewayAPI
from character_packs import CharacterPackService
from audio import AudioDeliveryPipeline, StubTtsBackend
from text import TextDeliveryPipeline
from channel import AgentBackend, ChannelService, create_backend_from_env
from character_packs import CharacterPackStore, CharacterRendererService
from datp import EventBus
from datp.commands import CommandDispatcher
from datp.server import DATPServer
from registry import RegistryService
from registry.store import DeviceStore

logger = logging.getLogger(__name__)


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
        self.tts = self.tts or StubTtsBackend()
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
        self.text_delivery = TextDeliveryPipeline(
            event_bus=self.event_bus,
            dispatcher=self.dispatcher,
        )
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
