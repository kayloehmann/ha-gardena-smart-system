"""DataUpdateCoordinator for the Gardena Smart System integration."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from aiogardenasmart import (
    Device,
    GardenaAuth,
    GardenaAuthenticationError,
    GardenaClient,
    GardenaConnectionError,
    GardenaException,
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
    app_blocked_issue_key="husqvarna_application_blocked",
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

    # Dispatch table for inbound MQTT commands.
    # Value = (control_type, command, needs_duration_param).
    # Adding a new action is a single-line change here.
    _MQTT_DISPATCH: ClassVar[dict[str, tuple[str, str, bool]]] = {
        "start_watering": ("VALVE_CONTROL", "START_SECONDS_TO_OVERRIDE", True),
        "stop_watering": ("VALVE_CONTROL", "STOP_UNTIL_NEXT_TASK", False),
        "turn_on": ("POWER_SOCKET_CONTROL", "START_SECONDS_TO_OVERRIDE", True),
        "turn_off": ("POWER_SOCKET_CONTROL", "STOP_UNTIL_NEXT_TASK", False),
        "park": ("MOWER_CONTROL", "PARK_UNTIL_FURTHER_NOTICE", False),
        "resume": ("MOWER_CONTROL", "START_DONT_OVERRIDE", False),
    }

    async def _async_handle_mqtt_command(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle inbound MQTT commands for Gardena devices.

        Expected payload: {"action": "start_watering", "duration": 30, "service_id": "..."}
        """
        action = payload.get("action", "")
        spec = self._MQTT_DISPATCH.get(action)
        if spec is None:
            _LOGGER.warning(
                "Unknown MQTT action '%s' for device %s",
                action,
                device_id,
            )
            return

        service_id = payload.get("service_id", device_id)
        duration = payload.get("duration")
        control_type, command, needs_duration = spec

        try:
            self.check_command_throttle()
        except HomeAssistantError:
            _LOGGER.warning("MQTT command throttled for %s", device_id)
            return

        # Count before dispatch — any failed PUT still counts against quota.
        self._api_budget.increment()

        kwargs: dict[str, int] = {}
        if needs_duration:
            minutes = int(duration) if duration else 60
            kwargs["seconds"] = minutes * 60

        try:
            await self._client.async_send_command(service_id, control_type, command, **kwargs)
        except GardenaException:
            _LOGGER.exception(
                "MQTT command '%s' failed for %s",
                action,
                device_id,
            )
            return
        _LOGGER.info(
            "MQTT command '%s' executed for %s",
            action,
            device_id,
        )
