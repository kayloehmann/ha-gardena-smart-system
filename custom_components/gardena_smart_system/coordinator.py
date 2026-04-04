"""DataUpdateCoordinator for the Gardena Smart System integration."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

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

_LOGGER = logging.getLogger(__name__)

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

    _MQTT_ACTIONS: ClassVar[set[str]] = {
        "start_watering", "stop_watering", "park",
        "resume", "turn_on", "turn_off",
    }

    async def _async_handle_mqtt_command(
        self, device_id: str, payload: dict[str, Any]
    ) -> None:
        """Handle inbound MQTT commands for Gardena devices.

        Expected payload: {"action": "start_watering", "duration": 30, "service_id": "..."}
        """
        action = payload.get("action", "")
        if action not in self._MQTT_ACTIONS:
            _LOGGER.warning(
                "Unknown MQTT action '%s' for device %s", action, device_id,
            )
            return

        service_id = payload.get("service_id", device_id)
        duration = payload.get("duration")

        try:
            self.check_command_throttle()
        except Exception:
            _LOGGER.warning("MQTT command throttled for %s", device_id)
            return

        try:
            if action == "start_watering":
                minutes = int(duration) if duration else 60
                await self._client.async_send_command(
                    service_id, "VALVE_CONTROL",
                    "START_SECONDS_TO_OVERRIDE",
                    seconds=minutes * 60,
                )
            elif action == "stop_watering":
                await self._client.async_send_command(
                    service_id, "VALVE_CONTROL",
                    "STOP_UNTIL_NEXT_TASK",
                )
            elif action == "turn_on":
                minutes = int(duration) if duration else 60
                await self._client.async_send_command(
                    service_id, "POWER_SOCKET_CONTROL",
                    "START_SECONDS_TO_OVERRIDE",
                    seconds=minutes * 60,
                )
            elif action == "turn_off":
                await self._client.async_send_command(
                    service_id, "POWER_SOCKET_CONTROL",
                    "STOP_UNTIL_NEXT_TASK",
                )
            elif action == "park":
                await self._client.async_send_command(
                    service_id, "MOWER_CONTROL",
                    "PARK_UNTIL_FURTHER_NOTICE",
                )
            elif action == "resume":
                await self._client.async_send_command(
                    service_id, "MOWER_CONTROL",
                    "START_DONT_OVERRIDE",
                )
            _LOGGER.info(
                "MQTT command '%s' executed for %s", action, device_id,
            )
        except Exception:
            _LOGGER.exception(
                "MQTT command '%s' failed for %s", action, device_id,
            )
