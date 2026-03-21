"""DataUpdateCoordinator for Husqvarna Automower devices."""

from __future__ import annotations

import logging
import time
from datetime import timedelta

import aiohttp
from aioautomower import (
    AutomowerClient,
    AutomowerDevice,
    AutomowerWebSocket,
)
from aioautomower.exceptions import (
    AutomowerAuthenticationError,
    AutomowerConnectionError,
    AutomowerRateLimitError,
)
from aiogardenasmart.auth import GardenaAuth

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    AUTOMOWER_RATE_LIMIT_COOLDOWN,
    AUTOMOWER_SCAN_INTERVAL,
    AUTOMOWER_SCAN_INTERVAL_WS_CONNECTED,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    DOMAIN,
    MIN_COMMAND_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class AutomowerCoordinator(DataUpdateCoordinator[dict[str, AutomowerDevice]]):
    """Manages data fetching and WebSocket updates for Automower devices.

    Uses the Automower Connect API v1, which has a separate rate limit
    budget (10,000 requests/month) from the Gardena Smart System API.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        websession: aiohttp.ClientSession,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_automower",
            update_interval=AUTOMOWER_SCAN_INTERVAL,
            config_entry=entry,
        )
        self._websession = websession
        self._auth = GardenaAuth(
            client_id=entry.data[CONF_CLIENT_ID],
            client_secret=entry.data[CONF_CLIENT_SECRET],
            websession=websession,
        )
        self._client = AutomowerClient(self._auth, websession)
        self._ws: AutomowerWebSocket | None = None
        self._ws_connected = False
        self._last_command_time: float = 0.0

    @property
    def client(self) -> AutomowerClient:
        """The REST API client (used by entity platforms to send commands)."""
        return self._client

    async def _async_update_data(self) -> dict[str, AutomowerDevice]:
        """Fetch the latest mower state from the REST API."""
        try:
            devices = await self._client.async_get_mowers()
        except AutomowerAuthenticationError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except AutomowerRateLimitError as err:
            self.update_interval = AUTOMOWER_RATE_LIMIT_COOLDOWN
            _LOGGER.warning(
                "Rate limited by Automower API, backing off to %s",
                AUTOMOWER_RATE_LIMIT_COOLDOWN,
            )
            raise UpdateFailed(
                f"Rate limited by Automower API, retrying in "
                f"{AUTOMOWER_RATE_LIMIT_COOLDOWN}: {err}"
            ) from err
        except AutomowerConnectionError as err:
            raise UpdateFailed(f"Cannot connect to Automower API: {err}") from err

        # Restore normal polling interval after a successful fetch
        normal_interval = (
            AUTOMOWER_SCAN_INTERVAL_WS_CONNECTED
            if self._ws_connected
            else AUTOMOWER_SCAN_INTERVAL
        )
        if self.update_interval != normal_interval:
            _LOGGER.debug(
                "Automower API responded successfully, restoring poll interval to %s",
                normal_interval,
            )
            self.update_interval = normal_interval

        # Start WebSocket on first successful fetch
        if not self._ws_connected:
            await self._async_start_websocket(devices)

        # Remove stale devices
        self._async_remove_stale_devices(devices)

        return devices

    def _async_remove_stale_devices(
        self, fresh_devices: dict[str, AutomowerDevice]
    ) -> None:
        """Remove HA device registry entries for mowers no longer in the API response."""
        if self.data is None:
            return

        stale_ids = set(self.data) - set(fresh_devices)
        if not stale_ids:
            return

        device_registry = dr.async_get(self.hass)
        for mower_id in stale_ids:
            old_device = self.data[mower_id]
            if not old_device.serial_number:
                continue
            ha_device = device_registry.async_get_device(
                identifiers={(DOMAIN, old_device.serial_number)}
            )
            if ha_device:
                _LOGGER.debug(
                    "Removing stale Automower device %s (%s) from device registry",
                    old_device.name,
                    old_device.serial_number,
                )
                device_registry.async_remove_device(ha_device.id)

    async def _async_start_websocket(
        self, devices: dict[str, AutomowerDevice]
    ) -> None:
        """Start the WebSocket for real-time updates."""
        # The Automower API provides a WebSocket URL via the /ws endpoint
        try:
            ws_url = f"wss://ws.openapi.husqvarna.dev/v1"
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Could not obtain Automower WebSocket URL, will rely on polling: %s",
                err,
            )
            return

        self._ws = AutomowerWebSocket(
            auth=self._auth,
            websession=self._websession,
            devices=devices,
            on_update=self._on_device_update,
            on_error=self._on_ws_error,
        )
        try:
            await self._ws.async_connect(ws_url)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Could not connect Automower WebSocket, will rely on polling: %s",
                err,
            )
            return

        self._ws_connected = True
        self.update_interval = AUTOMOWER_SCAN_INTERVAL_WS_CONNECTED
        _LOGGER.debug(
            "Automower WebSocket started, poll interval set to %s",
            AUTOMOWER_SCAN_INTERVAL_WS_CONNECTED,
        )
        ir.async_delete_issue(self.hass, DOMAIN, "automower_websocket_connection_failed")

    def _on_device_update(self, mower_id: str, device: AutomowerDevice) -> None:
        """Called by the WebSocket client when a mower state changes."""
        if self.data is not None:
            self.data[mower_id] = device
        self.async_set_updated_data(self.data or {})

    def _on_ws_error(self, err: Exception) -> None:
        """Called when the WebSocket connection fails unrecoverably."""
        _LOGGER.error("Automower WebSocket connection lost: %s", err)
        self._ws_connected = False
        self.update_interval = AUTOMOWER_SCAN_INTERVAL
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            "automower_websocket_connection_failed",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="automower_websocket_connection_failed",
        )

    async def async_shutdown(self) -> None:
        """Disconnect the WebSocket and clean up resources."""
        if self._ws:
            await self._ws.async_disconnect()
            self._ws = None
        self._ws_connected = False

    def check_command_throttle(self) -> None:
        """Raise if a command is sent too soon after the previous one."""
        now = time.monotonic()
        elapsed = now - self._last_command_time
        if elapsed < MIN_COMMAND_INTERVAL_SECONDS:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_throttled",
            )
        self._last_command_time = now
