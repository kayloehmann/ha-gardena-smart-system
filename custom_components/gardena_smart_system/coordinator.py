"""DataUpdateCoordinator for the Gardena Smart System integration."""

from __future__ import annotations

import logging
import time
from datetime import timedelta

import aiohttp
from aiogardenasmart import (
    Device,
    GardenaAuth,
    GardenaAuthenticationError,
    GardenaClient,
    GardenaConnectionError,
    GardenaRateLimitError,
    GardenaWebSocket,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_LOCATION_ID,
    DEFAULT_POLL_INTERVAL_GARDENA,
    DOMAIN,
    MIN_COMMAND_INTERVAL_SECONDS,
    OPT_POLL_INTERVAL_MINUTES,
    RATE_LIMIT_COOLDOWN,
    SCAN_INTERVAL,
    SCAN_INTERVAL_WS_CONNECTED,
)

_LOGGER = logging.getLogger(__name__)


class GardenaCoordinator(DataUpdateCoordinator[dict[str, Device]]):
    """Manages data fetching and WebSocket updates for one Gardena location.

    WebSocket is the primary update mechanism. The coordinator's regular
    polling interval acts as a fallback / health-check only.

    Implements dynamic-devices: new devices detected on any poll are surfaced
    to entity platforms via the standard coordinator listener mechanism.

    Implements stale-devices: devices that disappear from the API are removed
    from the HA device registry on the next successful poll.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        websession: aiohttp.ClientSession,
    ) -> None:
        """Initialize the coordinator."""
        custom_minutes = entry.options.get(OPT_POLL_INTERVAL_MINUTES)
        initial_interval = (
            timedelta(minutes=int(custom_minutes))
            if custom_minutes is not None
            else SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=initial_interval,
            config_entry=entry,
        )
        self._websession = websession
        self._auth = GardenaAuth(
            client_id=entry.data[CONF_CLIENT_ID],
            client_secret=entry.data[CONF_CLIENT_SECRET],
            websession=websession,
        )
        self._client = GardenaClient(self._auth, websession)
        self._location_id: str = entry.data[CONF_LOCATION_ID]
        self._ws: GardenaWebSocket | None = None
        self._ws_connected = False
        self._last_command_time: float = 0.0
        self._custom_poll_interval = self._get_custom_poll_interval(entry)
        self._stale_miss_counts: dict[str, int] = {}

    @staticmethod
    def _get_custom_poll_interval(entry: ConfigEntry) -> timedelta | None:
        """Return user-configured poll interval, or None for default."""
        minutes = entry.options.get(OPT_POLL_INTERVAL_MINUTES)
        if minutes is not None and minutes != DEFAULT_POLL_INTERVAL_GARDENA:
            return timedelta(minutes=int(minutes))
        return None

    @property
    def location_id(self) -> str:
        """The Gardena location ID this coordinator manages."""
        return self._location_id

    @property
    def client(self) -> GardenaClient:
        """The REST API client (used by entity platforms to send commands)."""
        return self._client

    async def _async_update_data(self) -> dict[str, Device]:
        """Fetch the latest device state from the REST API.

        Called on first load and as a polling fallback. The WebSocket keeps
        data current during normal operation.

        After each successful fetch:
        - Starts the WebSocket on the first call.
        - Removes devices from the HA device registry that are no longer
          returned by the API (stale-devices rule).
        - New devices in the response are automatically surfaced to entity
          platforms because coordinator listeners fire after this returns
          (dynamic-devices rule).
        """
        try:
            devices = await self._client.async_get_devices(self._location_id)
        except GardenaAuthenticationError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except GardenaRateLimitError as err:
            self.update_interval = RATE_LIMIT_COOLDOWN
            _LOGGER.warning(
                "Rate limited by Gardena API, backing off to %s",
                RATE_LIMIT_COOLDOWN,
            )
            raise UpdateFailed(
                f"Rate limited by Gardena API, retrying in {RATE_LIMIT_COOLDOWN}: {err}"
            ) from err
        except GardenaConnectionError as err:
            raise UpdateFailed(f"Cannot connect to Gardena API: {err}") from err

        # Restore normal polling interval after a successful fetch
        if self._custom_poll_interval is not None:
            normal_interval = self._custom_poll_interval
        elif self._ws_connected:
            normal_interval = SCAN_INTERVAL_WS_CONNECTED
        else:
            normal_interval = SCAN_INTERVAL
        if self.update_interval != normal_interval:
            _LOGGER.debug(
                "Gardena API responded successfully, restoring poll interval to %s",
                normal_interval,
            )
            self.update_interval = normal_interval

        # Start WebSocket on first successful fetch
        if not self._ws_connected:
            await self._async_start_websocket(devices)

        # Remove devices that disappeared from the API (stale-devices rule)
        self._async_remove_stale_devices(devices)

        return devices

    _STALE_THRESHOLD = 3  # Remove after this many consecutive misses

    def _async_remove_stale_devices(self, fresh_devices: dict[str, Device]) -> None:
        """Remove HA device registry entries for devices no longer in the API response.

        Devices must be absent from the API for _STALE_THRESHOLD consecutive
        polls before being removed, to avoid false removals on transient errors.
        Devices below the threshold are kept in fresh_devices so coordinator.data
        retains them for the next comparison.
        """
        if self.data is None:
            return  # First poll — no previous state to compare

        stale_ids = set(self.data) - set(fresh_devices)

        # Clear miss counts for devices that reappeared
        for device_id in list(self._stale_miss_counts):
            if device_id not in stale_ids:
                del self._stale_miss_counts[device_id]

        if not stale_ids:
            return

        device_registry = dr.async_get(self.hass)
        for device_id in stale_ids:
            self._stale_miss_counts[device_id] = (
                self._stale_miss_counts.get(device_id, 0) + 1
            )
            miss_count = self._stale_miss_counts[device_id]

            if miss_count < self._STALE_THRESHOLD:
                _LOGGER.debug(
                    "Gardena device %s absent from API (%d/%d before removal)",
                    device_id,
                    miss_count,
                    self._STALE_THRESHOLD,
                )
                # Keep device in fresh_devices so it stays in coordinator.data
                fresh_devices[device_id] = self.data[device_id]
                continue

            old_device = self.data[device_id]
            if not old_device.serial:
                del self._stale_miss_counts[device_id]
                continue
            ha_device = device_registry.async_get_device(
                identifiers={(DOMAIN, old_device.serial)}
            )
            if ha_device:
                _LOGGER.debug(
                    "Removing stale Gardena device %s (%s) from device registry",
                    old_device.name,
                    old_device.serial,
                )
                device_registry.async_remove_device(ha_device.id)
            del self._stale_miss_counts[device_id]

    async def _async_start_websocket(self, devices: dict[str, Device]) -> None:
        """Request a WebSocket URL and start listening for real-time updates."""
        try:
            ws_url = await self._client.async_get_websocket_url(self._location_id)
        except (GardenaAuthenticationError, GardenaConnectionError, GardenaRateLimitError) as err:
            _LOGGER.warning(
                "Could not obtain WebSocket URL, will rely on polling: %s", err
            )
            return

        self._ws = GardenaWebSocket(
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
                "Could not connect Gardena WebSocket, will rely on polling: %s", err
            )
            self._ws = None
            return
        self._ws_connected = True
        ws_interval = self._custom_poll_interval or SCAN_INTERVAL_WS_CONNECTED
        self.update_interval = ws_interval
        _LOGGER.debug(
            "Gardena WebSocket started for location %s, poll interval set to %s",
            self._location_id,
            ws_interval,
        )
        ir.async_delete_issue(self.hass, DOMAIN, "websocket_connection_failed")

    def _on_device_update(self, device_id: str, device: Device) -> None:
        """Called by the WebSocket client when a device state changes."""
        if self.data is not None:
            self.data[device_id] = device
        self.async_set_updated_data(self.data or {})

    def _on_ws_error(self, err: Exception) -> None:
        """Called when the WebSocket connection fails unrecoverably."""
        _LOGGER.error("Gardena WebSocket connection lost: %s", err)
        self._ws_connected = False
        self.update_interval = self._custom_poll_interval or SCAN_INTERVAL

        if isinstance(err, GardenaAuthenticationError):
            self.config_entry.async_start_reauth(self.hass)
            return

        ir.async_create_issue(
            self.hass,
            DOMAIN,
            "websocket_connection_failed",
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="websocket_connection_failed",
        )

    async def async_shutdown(self) -> None:
        """Disconnect the WebSocket and clean up resources."""
        if self._ws:
            await self._ws.async_disconnect()
            self._ws = None
        self._ws_connected = False

    def check_command_throttle(self) -> None:
        """Raise if a command is sent too soon after the previous one.

        Prevents automations and UI from rapid-firing commands that burn
        through the Husqvarna API quota.
        """
        now = time.monotonic()
        elapsed = now - self._last_command_time
        if elapsed < MIN_COMMAND_INTERVAL_SECONDS:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_throttled",
            )
        self._last_command_time = now

