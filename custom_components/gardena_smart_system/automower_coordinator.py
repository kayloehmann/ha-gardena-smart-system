"""DataUpdateCoordinator for Husqvarna Automower devices."""

from __future__ import annotations

from typing import Any

import aiohttp
from aioautomower.exceptions import (
    AutomowerAuthenticationError,
    AutomowerConnectionError,
    AutomowerRateLimitError,
)
from aiogardenasmart.auth import GardenaAuth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from aioautomower import (
    AutomowerClient,
    AutomowerDevice,
    AutomowerWebSocket,
)

from .base_coordinator import BaseSmartSystemCoordinator, CoordinatorConfig
from .const import (
    AUTOMOWER_RATE_LIMIT_COOLDOWN,
    AUTOMOWER_SCAN_INTERVAL,
    AUTOMOWER_SCAN_INTERVAL_WS_CONNECTED,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    DEFAULT_POLL_INTERVAL_AUTOMOWER,
    DOMAIN,
)

_AUTOMOWER_WS_URL = "wss://ws.openapi.husqvarna.dev/v1"

_AUTOMOWER_CONFIG = CoordinatorConfig(
    coordinator_name=f"{DOMAIN}_automower",
    api_label="Automower",
    scan_interval=AUTOMOWER_SCAN_INTERVAL,
    scan_interval_ws=AUTOMOWER_SCAN_INTERVAL_WS_CONNECTED,
    rate_limit_cooldown=AUTOMOWER_RATE_LIMIT_COOLDOWN,
    default_poll_minutes=DEFAULT_POLL_INTERVAL_AUTOMOWER,
    ws_issue_key="automower_websocket_connection_failed",
    auth_error_type=AutomowerAuthenticationError,
    connection_error_type=AutomowerConnectionError,
    rate_limit_error_type=AutomowerRateLimitError,
    device_serial_fn=lambda d: d.serial_number,
)


class AutomowerCoordinator(BaseSmartSystemCoordinator[AutomowerDevice]):
    """Manages data fetching and WebSocket updates for Automower devices."""

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
        super().__init__(hass, entry, websession, auth, _AUTOMOWER_CONFIG)
        self._client = AutomowerClient(auth, websession)

    @property
    def client(self) -> AutomowerClient:
        """The REST API client (used by entity platforms to send commands)."""
        return self._client

    async def _async_fetch_devices(self) -> dict[str, AutomowerDevice]:
        """Fetch mowers from the Automower API."""
        return await self._client.async_get_mowers()

    async def _async_get_ws_url(self, devices: dict[str, AutomowerDevice]) -> str:
        """Return the fixed Automower WebSocket URL."""
        return _AUTOMOWER_WS_URL

    def _create_websocket(
        self,
        auth: Any,
        websession: aiohttp.ClientSession,
        devices: dict[str, AutomowerDevice],
        on_update: Any,
        on_error: Any,
    ) -> AutomowerWebSocket:
        """Construct the Automower WebSocket client."""
        return AutomowerWebSocket(
            auth=auth,
            websession=websession,
            devices=devices,
            on_update=on_update,
            on_error=on_error,
        )
