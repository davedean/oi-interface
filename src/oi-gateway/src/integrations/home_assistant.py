"""Home Assistant adapter for oi-gateway.

This adapter allows oi-gateway to connect to Home Assistant instances
to control smart home devices, get states, and listen for events.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class HAEntity:
    """A Home Assistant entity."""
    entity_id: str
    state: str
    attributes: dict[str, Any]
    last_changed: str
    last_updated: str


@dataclass
class HAEvent:
    """A Home Assistant event."""
    event_type: str
    data: dict[str, Any]
    origin: str
    time_fired: str


@dataclass
class HAService:
    """A Home Assistant service."""
    domain: str
    service: str
    services: dict[str, Any]


@runtime_checkable
class HomeAssistantAdapterProtocol(Protocol):
    """Protocol for Home Assistant adapter implementations."""

    async def connect(self) -> bool:
        """Connect to the Home Assistant instance."""
        ...

    async def disconnect(self) -> None:
        """Disconnect from the Home Assistant instance."""
        ...

    async def get_states(self) -> list[HAEntity]:
        """Get all entity states."""
        ...

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a Home Assistant service."""
        ...

    async def listen_events(
        self,
        event_type: str | None,
        callback: Callable[[HAEvent], Any],
    ) -> str:
        """Listen for Home Assistant events."""
        ...


class HomeAssistantAdapterError(Exception):
    """Error in Home Assistant adapter."""
    pass


class HomeAssistantConnectionError(HomeAssistantAdapterError):
    """Failed to connect to Home Assistant."""
    pass


class HomeAssistantAPIError(HomeAssistantAdapterError):
    """Home Assistant API call failed."""
    pass


class HomeAssistantEventError(HomeAssistantAdapterError):
    """Failed to listen for events."""
    pass


class HomeAssistantAdapter:
    """Home Assistant adapter for smart home integration.

    Parameters
    ----------
    base_url : str
        Base URL of the Home Assistant instance (e.g., "http://homeassistant:8123").
    token : str
        Long-lived access token for authentication.
    timeout : float
        Default timeout for requests in seconds.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None
        self._connected = False
        self._event_handlers: dict[str, list[Callable[[HAEvent], asyncio.Future]]] = {}
        self._event_stream_task: asyncio.Task | None = None

    async def connect(self) -> bool:
        """Connect to the Home Assistant instance."""
        try:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                headers=self._get_headers(),
            )

            # Test connection with API config endpoint
            async with self._session.get(f"{self._base_url}/api/config") as resp:
                if resp.status == 200:
                    self._connected = True
                    logger.info("Connected to Home Assistant: %s", self._base_url)
                    return True
                else:
                    logger.warning("Home Assistant returned status %d", resp.status)
                    return False

        except aiohttp.ClientError as e:
            logger.warning("Failed to connect to Home Assistant: %s", e)
            self._connected = False
            return False
        except Exception as e:
            logger.error("Unexpected error connecting to Home Assistant: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from the Home Assistant instance."""
        if self._event_stream_task:
            self._event_stream_task.cancel()
            try:
                await self._event_stream_task
            except asyncio.CancelledError:
                pass
            self._event_stream_task = None

        if self._session:
            await self._session.close()
            self._session = None

        self._connected = False
        self._event_handlers.clear()
        logger.info("Disconnected from Home Assistant")

    async def get_states(self) -> list[HAEntity]:
        """Get all entity states from Home Assistant."""
        if not self._connected or not self._session:
            raise HomeAssistantConnectionError("Not connected to Home Assistant")

        try:
            async with self._session.get(f"{self._base_url}/api/states") as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise HomeAssistantAPIError(
                        f"Home Assistant API returned status {resp.status}: {text}"
                    )

                states = await resp.json()
                return [
                    HAEntity(
                        entity_id=state["entity_id"],
                        state=state["state"],
                        attributes=state.get("attributes", {}),
                        last_changed=state.get("last_changed", ""),
                        last_updated=state.get("last_updated", ""),
                    )
                    for state in states
                ]
        except aiohttp.ClientError as e:
            raise HomeAssistantConnectionError(f"Failed to get states: {e}") from e

    async def get_state(self, entity_id: str) -> HAEntity:
        """Get the state of a specific entity."""
        if not self._connected or not self._session:
            raise HomeAssistantConnectionError("Not connected to Home Assistant")

        try:
            async with self._session.get(
                f"{self._base_url}/api/states/{entity_id}"
            ) as resp:
                if resp.status == 404:
                    raise HomeAssistantAPIError(f"Entity not found: {entity_id}")
                if resp.status != 200:
                    text = await resp.text()
                    raise HomeAssistantAPIError(
                        f"Home Assistant API returned status {resp.status}: {text}"
                    )

                state = await resp.json()
                return HAEntity(
                    entity_id=state["entity_id"],
                    state=state["state"],
                    attributes=state.get("attributes", {}),
                    last_changed=state.get("last_changed", ""),
                    last_updated=state.get("last_updated", ""),
                )
        except aiohttp.ClientError as e:
            raise HomeAssistantConnectionError(f"Failed to get state: {e}") from e

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a Home Assistant service.

        Parameters
        ----------
        domain : str
            The domain of the service (e.g., "light", "switch").
        service : str
            The service to call (e.g., "turn_on", "turn_off").
        service_data : dict, optional
            Data to pass to the service.

        Returns
        -------
        dict
            Response from the service call.
        """
        if not self._connected or not self._session:
            raise HomeAssistantConnectionError("Not connected to Home Assistant")

        payload = service_data or {}

        try:
            async with self._session.post(
                f"{self._base_url}/api/services/{domain}/{service}",
                json=payload,
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise HomeAssistantAPIError(
                        f"Home Assistant service call failed: {text}"
                    )

                result = await resp.json()
                logger.info("Called service %s.%s", domain, service)
                return result
        except aiohttp.ClientError as e:
            raise HomeAssistantConnectionError(f"Failed to call service: {e}") from e

    async def list_services(self) -> dict[str, HAService]:
        """List all available services in Home Assistant."""
        if not self._connected or not self._session:
            raise HomeAssistantConnectionError("Not connected to Home Assistant")

        try:
            async with self._session.get(f"{self._base_url}/api/services") as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise HomeAssistantAPIError(
                        f"Home Assistant API returned status {resp.status}: {text}"
                    )

                services = await resp.json()
                result = {}
                for domain, domain_services in services.items():
                    for service_name, service_data in domain_services.items():
                        key = f"{domain}.{service_name}"
                        result[key] = HAService(
                            domain=domain,
                            service=service_name,
                            services=service_data,
                        )
                return result
        except aiohttp.ClientError as e:
            raise HomeAssistantConnectionError(f"Failed to list services: {e}") from e

    async def listen_events(
        self,
        event_type: str | None,
        callback: Callable[[HAEvent], Any],
    ) -> str:
        """Listen for Home Assistant events.

        Parameters
        ----------
        event_type : str, optional
            Specific event type to listen for (e.g., "state_changed").
            If None, listens for all events.
        callback : callable
            Async callable to handle events.

        Returns
        -------
        str
            Listener ID that can be used to unsubscribe.
        """
        if not self._connected:
            raise HomeAssistantConnectionError("Not connected to Home Assistant")

        listener_id = f"listener_{event_type or 'all'}_{id(callback)}"

        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []

        self._event_handlers[event_type].append(callback)

        # Start event stream if not already running
        if not self._event_stream_task:
            self._event_stream_task = asyncio.create_task(self._event_stream())

        logger.info("Listening for Home Assistant events: %s", event_type or "all")
        return listener_id

    def unlisten_events(self, listener_id: str) -> None:
        """Stop listening for events.

        Parameters
        ----------
        listener_id : str
            The listener ID returned from listen_events.
        """
        for event_type, handlers in self._event_handlers.items():
            self._event_handlers[event_type] = [
                h for h in handlers
                if f"listener_{event_type or 'all'}_{id(h)}" != listener_id
            ]

    async def fire_event(self, event_type: str, event_data: dict[str, Any]) -> None:
        """Fire a custom event in Home Assistant.

        Parameters
        ----------
        event_type : str
            Type of the event.
        event_data : dict
            Event data.
        """
        if not self._connected or not self._session:
            raise HomeAssistantConnectionError("Not connected to Home Assistant")

        try:
            async with self._session.post(
                f"{self._base_url}/api/events/{event_type}",
                json=event_data,
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise HomeAssistantAPIError(
                        f"Failed to fire event: {text}"
                    )
                logger.info("Fired event: %s", event_type)
        except aiohttp.ClientError as e:
            raise HomeAssistantConnectionError(f"Failed to fire event: {e}") from e

    async def _event_stream(self) -> None:
        """Stream events from Home Assistant."""
        if not self._session:
            return

        try:
            async with self._session.get(
                f"{self._base_url}/api/events",
                headers={"Accept": "text/event-stream"},
            ) as resp:
                if resp.status != 200:
                    logger.warning("Event stream returned status %d", resp.status)
                    return

                # Read SSE events
                async for line in resp.content:
                    if not line:
                        continue

                    line = line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue

                    try:
                        data = json.loads(line[5:])
                        event = HAEvent(
                            event_type=data.get("event_type", ""),
                            data=data.get("data", {}),
                            origin=data.get("origin", ""),
                            time_fired=data.get("time_fired", ""),
                        )

                        # Dispatch to handlers
                        for handler in self._event_handlers.get(event.event_type, []):
                            try:
                                await handler(event)
                            except Exception as e:
                                logger.error("Error in event handler: %s", e)

                        # Also call "all" handlers
                        for handler in self._event_handlers.get(None, []):
                            try:
                                await handler(event)
                            except Exception as e:
                                logger.error("Error in event handler: %s", e)

                    except json.JSONDecodeError:
                        continue

        except asyncio.CancelledError:
            logger.info("Event stream cancelled")
        except Exception as e:
            logger.error("Error in event stream: %s", e)

    def _get_headers(self) -> dict[str, str]:
        """Get HTTP headers including authentication token."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    @property
    def is_connected(self) -> bool:
        """Check if connected to Home Assistant."""
        return self._connected

    @property
    def base_url(self) -> str:
        """Get the base URL."""
        return self._base_url


# Import json for the event stream
import json