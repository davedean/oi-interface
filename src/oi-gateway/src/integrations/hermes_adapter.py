"""Hermes/Rhasspy voice integration adapter for oi-gateway.

Hermes is the message bus protocol used by Rhasspy and other Snips-derived
voice assistants. This adapter allows oi-gateway to communicate with the
Hermes MQTT message bus.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

import aiohttp

try:
    import paho.mqtt.client as mqtt
    HAS_PAHO = True
except ImportError:
    mqtt = None  # type: ignore
    HAS_PAHO = False

logger = logging.getLogger(__name__)


class HermesDependencyError(ImportError):
    """Raised when paho-mqtt is not installed but Hermes adapter is used."""
    pass


@dataclass
class HermesMessage:
    """A Hermes MQTT message."""
    topic: str
    payload: dict[str, Any]
    site_id: str | None = None


@dataclass
class HermesIntent:
    """A recognized voice intent from Hermes."""
    intent_name: str
    slots: dict[str, Any]
    site_id: str
    session_id: str | None = None


@runtime_checkable
class HermesMQTTAdapterProtocol(Protocol):
    """Protocol for Hermes MQTT adapter implementations."""

    async def connect(self) -> bool:
        """Connect to the Hermes MQTT broker."""
        ...

    async def disconnect(self) -> None:
        """Disconnect from the Hermes MQTT broker."""
        ...

    async def subscribe(self, topic: str) -> bool:
        """Subscribe to a Hermes topic."""
        ...

    async def publish(self, topic: str, payload: dict[str, Any]) -> bool:
        """Publish to a Hermes topic."""
        ...


class HermesAdapterError(Exception):
    """Error in Hermes adapter."""
    pass


class HermesConnectionError(HermesAdapterError):
    """Failed to connect to Hermes MQTT broker."""
    pass


class HermesSubscribeError(HermesAdapterError):
    """Failed to subscribe to Hermes topic."""
    pass


class HermesPublishError(HermesAdapterError):
    """Failed to publish to Hermes topic."""
    pass


class HermesMQTTAdapter:
    """Hermes MQTT adapter for Rhasspy voice integration.

    This adapter connects to the Hermes protocol MQTT broker used by Rhasspy
    and other Snips-derived voice assistants.

    Parameters
    ----------
    mqtt_host : str
        MQTT broker hostname.
    mqtt_port : int
        MQTT broker port (default: 1883).
    mqtt_username : str, optional
        MQTT username for authentication.
    mqtt_password : str, optional
        MQTT password for authentication.
    site_id : str
        Site ID for this gateway.
    """

    def __init__(
        self,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        mqtt_username: str | None = None,
        mqtt_password: str | None = None,
        site_id: str = "default",
    ) -> None:
        self._mqtt_host = mqtt_host
        self._mqtt_port = mqtt_port
        self._mqtt_username = mqtt_username
        self._mqtt_password = mqtt_password
        self._site_id = site_id

        self._client: mqtt.Client | None = None
        self._connected = False
        self._message_handlers: dict[str, Callable[[HermesMessage], asyncio.Future]] = {}
        self._pending_message: asyncio.Future[HermesMessage] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        # Hermes topic patterns
        self._topics = {
            "intent": "hermes/intent/#",
            "tts": "hermes/tts/#",
            "asr": "hermes/asr/#",
            "hotword": "hermes/hotword/#",
            "dialogue": "hermes/dialogueManager/#",
            "audio": "hermes/audioServer/#",
        }

    async def connect(self) -> bool:
        """Connect to the Hermes MQTT broker."""
        if not HAS_PAHO:
            raise HermesDependencyError(
                "paho-mqtt is required for Hermes adapter. "
                "Install with: pip install paho-mqtt"
            )
        self._loop = asyncio.get_event_loop()

        # Create MQTT client with callbacks
        client_id = f"oi-gateway-{self._site_id}"
        self._client = mqtt.Client(client_id=client_id)

        if self._mqtt_username and self._mqtt_password:
            self._client.username_pw_set(self._mqtt_username, self._mqtt_password)

        # Set up callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # Connect with timeout
        try:
            loop = asyncio.get_event_loop()
            connect_future = asyncio.Future()

            def on_connect_callback(client, userdata, flags, rc):
                if rc == 0:
                    self._connected = True
                loop.call_soon_threadsafe(connect_future.set_result, rc)

            self._client.on_connect = on_connect_callback

            # Connect in thread pool since paho-mqtt is blocking
            await asyncio.to_thread(
                self._client.connect,
                self._mqtt_host,
                self._mqtt_port,
                keepalive=60,
            )

            # Wait for connection with timeout
            try:
                await asyncio.wait_for(connect_future, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("MQTT connection timed out")
                return False

            if self._connected:
                # Start MQTT loop in background thread
                await asyncio.to_thread(self._client.loop_start)
                logger.info("Connected to Hermes MQTT broker: %s:%d", self._mqtt_host, self._mqtt_port)
                return True
            return False

        except Exception as e:
            logger.error("Failed to connect to Hermes MQTT broker: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from the Hermes MQTT broker."""
        if self._client:
            try:
                await asyncio.to_thread(self._client.loop_stop)
                await asyncio.to_thread(self._client.disconnect)
            except Exception as e:
                logger.warning("Error disconnecting MQTT client: %s", e)
            finally:
                self._client = None
        self._connected = False
        logger.info("Disconnected from Hermes MQTT broker")

    async def subscribe(self, topic: str) -> bool:
        """Subscribe to a Hermes topic."""
        if not self._connected or not self._client:
            raise HermesConnectionError("Not connected to Hermes MQTT broker")

        try:
            result = await asyncio.to_thread(
                self._client.subscribe,
                topic,
                qos=1,
            )
            if result[0] == mqtt.MQTT_ERR_SUCCESS:
                logger.info("Subscribed to Hermes topic: %s", topic)
                return True
            else:
                raise HermesSubscribeError(f"MQTT subscribe failed with code {result[0]}")
        except Exception as e:
            raise HermesSubscribeError(f"Failed to subscribe to {topic}: {e}") from e

    async def publish(self, topic: str, payload: dict[str, Any]) -> bool:
        """Publish to a Hermes topic."""
        if not self._connected or not self._client:
            raise HermesConnectionError("Not connected to Hermes MQTT broker")

        try:
            payload_json = json.dumps(payload)
            result = await asyncio.to_thread(
                self._client.publish,
                topic,
                payload_json,
                qos=1,
            )
            if result[0] == mqtt.MQTT_ERR_SUCCESS:
                logger.debug("Published to Hermes topic %s: %s", topic, payload_json)
                return True
            else:
                raise HermesPublishError(f"MQTT publish failed with code {result[0]}")
        except Exception as e:
            raise HermesPublishError(f"Failed to publish to {topic}: {e}") from e

    async def handle_message(self, message: HermesMessage) -> None:
        """Handle a received Hermes message.

        Parameters
        ----------
        message : HermesMessage
            The message to handle.
        """
        # Find registered handler for this topic pattern
        for topic_pattern, handler in self._message_handlers.items():
            if self._match_topic(message.topic, topic_pattern):
                try:
                    await handler(message)
                except Exception as e:
                    logger.error("Error handling message: %s", e)

    def register_handler(
        self,
        topic_pattern: str,
        handler: Callable[[HermesMessage], asyncio.Future],
    ) -> None:
        """Register a handler for a topic pattern.

        Parameters
        ----------
        topic_pattern : str
            MQTT topic pattern (supports # and + wildcards).
        handler : callable
            Async callable that handles the message.
        """
        self._message_handlers[topic_pattern] = handler

    def unregister_handler(self, topic_pattern: str) -> None:
        """Unregister a handler for a topic pattern."""
        self._message_handlers.pop(topic_pattern, None)

    async def listen_intents(self, callback: Callable[[HermesIntent], Any]) -> None:
        """Listen for intent messages from Hermes.

        Parameters
        ----------
        callback : callable
            Async callable to handle recognized intents.
        """
        await self.subscribe("hermes/intent/#")

        async def intent_handler(message: HermesMessage):
            try:
                intent = HermesIntent(
                    intent_name=message.payload.get("intent", {}).get("intentName", ""),
                    slots=message.payload.get("slots", {}),
                    site_id=message.payload.get("siteId", self._site_id),
                    session_id=message.payload.get("sessionId"),
                )
                await callback(intent)
            except Exception as e:
                logger.error("Error processing intent: %s", e)

        self.register_handler("hermes/intent/#", intent_handler)

    async def speak(self, text: str, site_id: str | None = None) -> bool:
        """Send text to be spoken via TTS.

        Parameters
        ----------
        text : str
            Text to speak.
        site_id : str, optional
            Site ID to speak on (defaults to configured site_id).
        """
        site_id = site_id or self._site_id
        topic = f"hermes/tts/say"
        payload = {
            "text": text,
            "siteId": site_id,
        }
        return await self.publish(topic, payload)

    async def startListening(self, site_id: str | None = None) -> bool:
        """Start listening for voice commands.

        Parameters
        ----------
        site_id : str, optional
            Site ID to start listening on.
        """
        site_id = site_id or self._site_id
        topic = f"hermes/dialogueManager/startListening"
        payload = {"siteId": site_id}
        return await self.publish(topic, payload)

    async def endSession(self, session_id: str, text: str | None = None) -> bool:
        """End a dialogue session.

        Parameters
        ----------
        session_id : str
            Session ID to end.
        text : str, optional
            Optional text to speak before ending.
        """
        topic = f"hermes/dialogueManager/endSession"
        payload = {"sessionId": session_id}
        if text:
            payload["text"] = text
        return await self.publish(topic, payload)

    def _on_connect(self, client, userdata, flags, rc):
        """Callback for when the client connects to the broker."""
        if rc == 0:
            self._connected = True
            logger.info("Connected to MQTT broker")
        else:
            logger.error("Failed to connect, return code %d", rc)

    def _on_disconnect(self, client, userdata, rc):
        """Callback for when the client disconnects from the broker."""
        self._connected = False
        logger.warning("Disconnected from MQTT broker with code %d", rc)

    def _on_message(self, client, userdata, msg):
        """Callback for when a message is received from the broker."""
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode("utf-8"))

            site_id = payload.get("siteId", self._site_id)

            message = HermesMessage(
                topic=topic,
                payload=payload,
                site_id=site_id,
            )

            # Schedule async handling
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self.handle_message(message),
                    self._loop,
                )
        except Exception as e:
            logger.error("Error processing MQTT message: %s", e)

    def _match_topic(self, topic: str, pattern: str) -> bool:
        """Check if a topic matches a pattern."""
        # Simple matching - convert MQTT wildcards to regex
        import re
        pattern_regex = pattern.replace("#", ".*").replace("+", "[^/]+")
        return re.match(f"^{pattern_regex}$", topic) is not None

    @property
    def is_connected(self) -> bool:
        """Check if connected to Hermes MQTT broker."""
        return self._connected

    @property
    def site_id(self) -> str:
        """Get the site ID."""
        return self._site_id