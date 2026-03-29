"""Shared base coordinator for Gardena Smart System and Automower integrations."""

from __future__ import annotations

import logging
import time
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, MIN_COMMAND_INTERVAL_SECONDS, OPT_POLL_INTERVAL_MINUTES

_LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True)
class CoordinatorConfig:
    """Configuration that varies between Gardena and Automower coordinators."""

    coordinator_name: str
    api_label: str
    scan_interval: timedelta
    scan_interval_ws: timedelta
    rate_limit_cooldown: timedelta
    default_poll_minutes: int
    ws_issue_key: str
    auth_error_type: type[Exception]
    connection_error_type: type[Exception]
    rate_limit_error_type: type[Exception]
    device_serial_fn: Callable[[Any], str | None]


class BaseSmartSystemCoordinator[DeviceT](DataUpdateCoordinator[dict[str, DeviceT]]):
    """Base coordinator with shared WebSocket, polling, stale-device, and throttle logic.

    Subclasses provide:
    - _async_fetch_devices(): the actual API call to get devices
    - _async_get_ws_url(devices): obtain the WebSocket URL
    - _create_websocket(...): construct the WebSocket client
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        websession: aiohttp.ClientSession,
        auth: Any,
        config: CoordinatorConfig,
    ) -> None:
        """Initialize the coordinator."""
        self._config = config
        custom_minutes = entry.options.get(OPT_POLL_INTERVAL_MINUTES)
        initial_interval = (
            timedelta(minutes=int(custom_minutes))
            if custom_minutes is not None
            else config.scan_interval
        )
        super().__init__(
            hass,
            _LOGGER,
            name=config.coordinator_name,
            update_interval=initial_interval,
            config_entry=entry,
        )
        self._websession = websession
        self._auth = auth
        self._ws: Any = None
        self._ws_connected = False
        self._last_command_time: float = 0.0
        self._stale_miss_counts: dict[str, int] = {}
        self._custom_poll_interval: timedelta | None = (
            timedelta(minutes=int(custom_minutes))
            if custom_minutes is not None and int(custom_minutes) != config.default_poll_minutes
            else None
        )
        self._rate_limit_hits: int = 0

    # ── Public properties ──────────────────────────────────────────────

    @property
    def ws_connected(self) -> bool:
        """Whether the WebSocket connection is active."""
        return self._ws_connected

    @property
    def last_command_time(self) -> float:
        """Monotonic timestamp of the last API command."""
        return self._last_command_time

    @property
    def stale_miss_counts(self) -> dict[str, int]:
        """Per-device consecutive miss counts for stale-device detection."""
        return self._stale_miss_counts

    # ── Abstract methods (subclass must implement) ─────────────────────

    @abstractmethod
    async def _async_fetch_devices(self) -> dict[str, DeviceT]:
        """Fetch devices from the API."""

    @abstractmethod
    async def _async_get_ws_url(self, devices: dict[str, DeviceT]) -> str:
        """Return the WebSocket URL."""

    @abstractmethod
    def _create_websocket(
        self,
        auth: Any,
        websession: aiohttp.ClientSession,
        devices: dict[str, DeviceT],
        on_update: Any,
        on_error: Any,
    ) -> Any:
        """Construct the WebSocket client."""

    # ── Core coordinator logic ─────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, DeviceT]:
        """Fetch the latest device state from the REST API."""
        cfg = self._config
        try:
            devices = await self._async_fetch_devices()
        except cfg.auth_error_type as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except cfg.rate_limit_error_type as err:
            self._rate_limit_hits += 1
            backoff = min(
                cfg.rate_limit_cooldown,
                timedelta(minutes=5) * (2 ** (self._rate_limit_hits - 1)),
            )
            self.update_interval = backoff
            _LOGGER.warning(
                "Rate limited by %s API (hit #%d), backing off to %s",
                cfg.api_label,
                self._rate_limit_hits,
                backoff,
            )
            raise UpdateFailed(
                f"Rate limited by {cfg.api_label} API, retrying in {backoff}: {err}"
            ) from err
        except cfg.connection_error_type as err:
            raise UpdateFailed(f"Cannot connect to {cfg.api_label} API: {err}") from err

        # Reset rate-limit counter and restore normal polling interval
        self._rate_limit_hits = 0
        if self._custom_poll_interval is not None:
            normal_interval = self._custom_poll_interval
        elif self._ws_connected:
            normal_interval = cfg.scan_interval_ws
        else:
            normal_interval = cfg.scan_interval
        if self.update_interval != normal_interval:
            _LOGGER.debug(
                "%s API responded successfully, restoring poll interval to %s",
                cfg.api_label,
                normal_interval,
            )
            self.update_interval = normal_interval

        # Start WebSocket on first successful fetch
        if not self._ws_connected:
            await self._async_start_websocket(devices)

        # Remove devices that disappeared from the API (stale-devices rule)
        self._async_remove_stale_devices(devices)

        return devices

    _STALE_THRESHOLD = 3

    def _async_remove_stale_devices(self, fresh_devices: dict[str, DeviceT]) -> None:
        """Remove HA device registry entries for devices no longer in the API response.

        Devices must be absent for _STALE_THRESHOLD consecutive polls before removal.
        """
        if self.data is None:
            return  # type: ignore[unreachable]

        stale_ids = set(self.data) - set(fresh_devices)

        for device_id in list(self._stale_miss_counts):
            if device_id not in stale_ids:
                del self._stale_miss_counts[device_id]

        if not stale_ids:
            return

        device_registry = dr.async_get(self.hass)
        for device_id in stale_ids:
            self._stale_miss_counts[device_id] = self._stale_miss_counts.get(device_id, 0) + 1
            miss_count = self._stale_miss_counts[device_id]

            if miss_count < self._STALE_THRESHOLD:
                _LOGGER.debug(
                    "%s device %s absent from API (%d/%d before removal)",
                    self._config.api_label,
                    device_id,
                    miss_count,
                    self._STALE_THRESHOLD,
                )
                fresh_devices[device_id] = self.data[device_id]
                continue

            old_device = self.data[device_id]
            serial = self._config.device_serial_fn(old_device)
            if not serial:
                del self._stale_miss_counts[device_id]
                continue
            ha_device = device_registry.async_get_device(identifiers={(DOMAIN, serial)})
            if ha_device:
                _LOGGER.debug(
                    "Removing stale %s device %s (%s) from device registry",
                    self._config.api_label,
                    getattr(old_device, "name", device_id),
                    serial,
                )
                device_registry.async_remove_device(ha_device.id)
            del self._stale_miss_counts[device_id]

    async def _async_start_websocket(self, devices: dict[str, DeviceT]) -> None:
        """Start the WebSocket for real-time updates."""
        cfg = self._config
        try:
            ws_url = await self._async_get_ws_url(devices)
        except (cfg.auth_error_type, cfg.connection_error_type, cfg.rate_limit_error_type) as err:
            _LOGGER.warning(
                "Could not obtain %s WebSocket URL, will rely on polling: %s",
                cfg.api_label,
                err,
            )
            return

        self._ws = self._create_websocket(
            auth=self._auth,
            websession=self._websession,
            devices=devices,
            on_update=self._on_device_update,
            on_error=self._on_ws_error,
        )
        try:
            await self._ws.async_connect(ws_url)
        except Exception as err:
            _LOGGER.warning(
                "Could not connect %s WebSocket, will rely on polling: %s",
                cfg.api_label,
                err,
            )
            self._ws = None
            return

        self._ws_connected = True
        ws_interval = self._custom_poll_interval or cfg.scan_interval_ws
        self.update_interval = ws_interval
        ir.async_delete_issue(self.hass, DOMAIN, cfg.ws_issue_key)
        _LOGGER.debug(
            "%s WebSocket started, poll interval set to %s",
            cfg.api_label,
            ws_interval,
        )

    def _on_device_update(self, device_id: str, device: DeviceT) -> None:
        """Called by the WebSocket client when a device state changes."""
        if self.data is not None:
            self.data[device_id] = device
        self.async_set_updated_data(self.data or {})

    def _on_ws_error(self, err: Exception) -> None:
        """Called when the WebSocket connection fails unrecoverably."""
        cfg = self._config
        _LOGGER.error("%s WebSocket connection lost: %s", cfg.api_label, err)
        self._ws_connected = False
        self.update_interval = self._custom_poll_interval or cfg.scan_interval

        if isinstance(err, cfg.auth_error_type):
            self.config_entry.async_start_reauth(self.hass)
            return

        ir.async_create_issue(
            self.hass,
            DOMAIN,
            cfg.ws_issue_key,
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="websocket_connection_failed",
        )
        _LOGGER.warning(
            "%s WebSocket connection lost, falling back to polling: %s",
            cfg.api_label,
            err,
        )

    async def async_shutdown(self) -> None:
        """Disconnect the WebSocket, revoke token, and clean up resources."""
        if self._ws:
            await self._ws.async_disconnect()
            self._ws = None
        self._ws_connected = False
        try:
            await self._auth.async_revoke_token()
        except Exception:
            _LOGGER.debug("Token revocation failed during shutdown")

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
