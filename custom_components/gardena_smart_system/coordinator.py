"""DataUpdateCoordinator for the Gardena Smart System integration."""

from __future__ import annotations

from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from aiogardenasmart import (
    Device,
    GardenaAuth,
    GardenaAuthenticationError,
    GardenaClient,
    GardenaConnectionError,
    GardenaRateLimitError,
    GardenaWebSocket,
)

from .base_coordinator import BaseSmartSystemCoordinator, CoordinatorConfig
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_LOCATION_ID,
    DEFAULT_POLL_INTERVAL_GARDENA,
    DOMAIN,
    RATE_LIMIT_COOLDOWN,
    SCAN_INTERVAL,
    SCAN_INTERVAL_WS_CONNECTED,
)

_GARDENA_CONFIG = CoordinatorConfig(
    coordinator_name=DOMAIN,
    api_label="Gardena",
    scan_interval=SCAN_INTERVAL,
    scan_interval_ws=SCAN_INTERVAL_WS_CONNECTED,
    rate_limit_cooldown=RATE_LIMIT_COOLDOWN,
    default_poll_minutes=DEFAULT_POLL_INTERVAL_GARDENA,
    ws_issue_key="websocket_connection_failed",
    auth_error_type=GardenaAuthenticationError,
    connection_error_type=GardenaConnectionError,
    rate_limit_error_type=GardenaRateLimitError,
    device_serial_fn=lambda d: d.serial,
)


class GardenaCoordinator(BaseSmartSystemCoordinator[Device]):
    """Manages data fetching and WebSocket updates for one Gardena location."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        websession: aiohttp.ClientSession,
    ) -> None:
        """Initialize the coordinator."""
        auth = GardenaAuth(
            client_id=entry.data[CONF_CLIENT_ID],
            client_secret=entry.data[CONF_CLIENT_SECRET],
            websession=websession,
        )
        super().__init__(hass, entry, websession, auth, _GARDENA_CONFIG)
        self._client = GardenaClient(auth, websession)
        self._location_id: str = entry.data[CONF_LOCATION_ID]

    @property
    def location_id(self) -> str:
        """The Gardena location ID this coordinator manages."""
        return self._location_id

    @property
    def client(self) -> GardenaClient:
        """The REST API client (used by entity platforms to send commands)."""
        return self._client

    async def _async_fetch_devices(self) -> dict[str, Device]:
        """Fetch devices from the Gardena API."""
        return await self._client.async_get_devices(self._location_id)

    async def _async_get_ws_url(self, devices: dict[str, Device]) -> str:
        """Obtain the WebSocket URL from the Gardena API."""
        return await self._client.async_get_websocket_url(self._location_id)

    def _create_websocket(
        self,
        auth: Any,
        websession: aiohttp.ClientSession,
        devices: dict[str, Device],
        on_update: Any,
        on_error: Any,
    ) -> GardenaWebSocket:
        """Construct the Gardena WebSocket client."""
        return GardenaWebSocket(
            auth=auth,
            websession=websession,
            devices=devices,
            on_update=on_update,
            on_error=on_error,
        )
