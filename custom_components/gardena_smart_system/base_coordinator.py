"""Shared base coordinator for Gardena Smart System and Automower integrations."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    API_BUDGET_MONTHLY,
    BUDGET_SAVE_DELAY_SECONDS,
    COMMAND_BURST_CAPACITY,
    DEFAULT_MQTT_TOPIC_PREFIX,
    DOMAIN,
    MIN_COMMAND_INTERVAL_SECONDS,
    OPT_MQTT_ENABLE,
    STORAGE_VERSION_API_BUDGET,
    OPT_MQTT_PUBLISH_STATES,
    OPT_MQTT_SUBSCRIBE_COMMANDS,
    OPT_MQTT_TOPIC_PREFIX,
    OPT_POLL_INTERVAL_MINUTES,
    WS_WATCHDOG_CHECK_INTERVAL,
    WS_WATCHDOG_TIMEOUT_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class ApiBudgetTracker:
    """Track the number of API requests made this calendar month.

    Uses Home Assistant's Store with delayed saves so that every increment
    does not trigger a disk write — at most one write per BUDGET_SAVE_DELAY_SECONDS.
    The counter resets automatically when a new calendar month starts.
    """

    def __init__(self, store: Store, budget: int = API_BUDGET_MONTHLY) -> None:
        self._store = store
        self._budget = budget
        self._month: str = ""
        self._count: int = 0
        self._loaded = False

    async def async_load(self) -> None:
        """Load persisted data from disk, resetting if the month rolled over."""
        data = await self._store.async_load()
        current_month = dt_util.now().strftime("%Y-%m")
        if data and data.get("month") == current_month:
            self._month = current_month
            self._count = data.get("request_count", 0)
        else:
            self._month = current_month
            self._count = 0
        self._loaded = True

    def increment(self, count: int = 1) -> None:
        """Record that *count* API requests were made.

        Automatically resets if the calendar month has changed since the last
        call. Schedules a delayed save so that rapid increments do not cause
        excessive I/O.
        """
        current_month = dt_util.now().strftime("%Y-%m")
        if current_month != self._month:
            self._month = current_month
            self._count = 0
        self._count += count
        self._store.async_delay_save(
            lambda: {"month": self._month, "request_count": self._count},
            delay=BUDGET_SAVE_DELAY_SECONDS,
        )

    @property
    def request_count(self) -> int:
        """Total API requests in the current calendar month."""
        return self._count

    @property
    def month(self) -> str:
        """Current tracking month as YYYY-MM."""
        return self._month

    @property
    def budget(self) -> int:
        """Monthly API request budget."""
        return self._budget

    @property
    def remaining_percent(self) -> float:
        """Remaining budget as a percentage (0.0 – 100.0)."""
        return max(0.0, (1 - self._count / self._budget) * 100)


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
        # Token bucket for command throttling — starts full so a cold-start
        # burst is permitted. Refills at 1 token per MIN_COMMAND_INTERVAL_SECONDS.
        self._command_tokens: float = float(COMMAND_BURST_CAPACITY)
        self._command_tokens_updated: float = time.monotonic()
        self._stale_miss_counts: dict[str, int] = {}
        self._custom_poll_interval: timedelta | None = (
            timedelta(minutes=int(custom_minutes))
            if custom_minutes is not None and int(custom_minutes) != config.default_poll_minutes
            else None
        )
        self._rate_limit_hits: int = 0
        self._ws_reconnect_task: asyncio.Task[None] | None = None
        self._mqtt_bridge: Any = None
        self._ws_watchdog_unsub: CALLBACK_TYPE | None = None
        self._cached_ws_url: str | None = None
        self._ws_connect_lock = asyncio.Lock()
        self._api_budget = ApiBudgetTracker(
            Store(hass, STORAGE_VERSION_API_BUDGET, f"{DOMAIN}.{entry.entry_id}.api_budget"),
        )

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
    def api_budget(self) -> ApiBudgetTracker:
        """Return the API budget tracker."""
        return self._api_budget

    @property
    def stale_miss_counts(self) -> dict[str, int]:
        """Per-device consecutive miss counts for stale-device detection."""
        return self._stale_miss_counts

    _ws_url_is_api_call: bool = True

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
            self._apply_rate_limit_backoff(err)
            raise UpdateFailed(
                f"Rate limited by {cfg.api_label} API, retrying in {self.update_interval}: {err}"
            ) from err
        except cfg.connection_error_type as err:
            raise UpdateFailed(f"Cannot connect to {cfg.api_label} API: {err}") from err

        self._api_budget.increment()

        # Reset rate-limit counter and restore normal polling interval.
        # Custom poll interval only applies to REST fallback — when WebSocket
        # is active, data arrives via push and only a 6-hour health check is
        # needed.  Using a short custom interval with WS connected would burn
        # through the API rate limit budget for no benefit.
        self._rate_limit_hits = 0
        if self._ws_connected:
            normal_interval = cfg.scan_interval_ws
        elif self._custom_poll_interval is not None:
            normal_interval = self._custom_poll_interval
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

        # Start MQTT bridge on first successful fetch
        if self._mqtt_bridge is None:
            await self._async_start_mqtt_bridge()
        if self._mqtt_bridge and self._mqtt_bridge.is_active:
            self.hass.async_create_task(self._mqtt_bridge.async_publish_all_devices(devices))

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
        """Start the WebSocket for real-time updates.

        Protected by a lock to prevent parallel connect attempts (e.g. watchdog +
        poll cycle racing).  The WebSocket URL is cached and reused as long as
        the auth token is still valid; a fresh URL is fetched only when the token
        was refreshed or the cached URL fails to connect.
        """
        if self._ws_connect_lock.locked():
            _LOGGER.debug(
                "%s WebSocket connect already in progress, skipping",
                self._config.api_label,
            )
            return

        async with self._ws_connect_lock:
            await self._async_start_websocket_locked(devices)

    async def _async_start_websocket_locked(self, devices: dict[str, DeviceT]) -> None:
        """Inner WebSocket start logic (must be called under _ws_connect_lock)."""
        cfg = self._config

        # Reuse cached WS URL while the auth token is still valid
        ws_url = self._cached_ws_url if self._auth.is_token_valid and self._cached_ws_url else None

        if ws_url is None:
            try:
                ws_url = await self._async_get_ws_url(devices)
            except cfg.rate_limit_error_type as err:
                self._apply_rate_limit_backoff(err)
                return
            except (cfg.auth_error_type, cfg.connection_error_type) as err:
                _LOGGER.warning(
                    "Could not obtain %s WebSocket URL, will rely on polling: %s",
                    cfg.api_label,
                    err,
                )
                return
            self._cached_ws_url = ws_url
            if self._ws_url_is_api_call:
                self._api_budget.increment()

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
            # Invalidate cached URL so the next attempt fetches a fresh one
            self._cached_ws_url = None
            return

        self._ws_connected = True
        self._cancel_ws_reconnect()
        self._start_ws_watchdog()
        # Always use the long WS health-check interval when connected — the
        # custom poll interval is for REST fallback only.
        ws_interval = cfg.scan_interval_ws
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
        if self._mqtt_bridge and self._mqtt_bridge.is_active:
            self.hass.async_create_task(
                self._mqtt_bridge.async_publish_device_state(device_id, device)
            )
        self.async_set_updated_data(self.data or {})

    def _on_ws_error(self, err: Exception) -> None:
        """Called when the WebSocket connection fails unrecoverably."""
        cfg = self._config
        _LOGGER.error("%s WebSocket connection lost: %s", cfg.api_label, err)
        self._ws_connected = False
        self._ws = None
        self._cached_ws_url = None
        self._stop_ws_watchdog()
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
        self._schedule_ws_reconnect()

    def _apply_rate_limit_backoff(self, err: Exception) -> None:
        """Apply exponential backoff for a rate-limit error.

        Shared between the poll cycle (_async_update_data) and WebSocket URL
        fetching so that a 429 from the auth token endpoint triggers the same
        backoff as a 429 from a normal API call.
        """
        cfg = self._config
        self._rate_limit_hits += 1
        backoff = min(
            cfg.rate_limit_cooldown,
            timedelta(minutes=5) * (2 ** (self._rate_limit_hits - 1)),
        )
        self.update_interval = backoff
        _LOGGER.warning(
            "Rate limited by %s API (hit #%d), backing off to %s: %s",
            cfg.api_label,
            self._rate_limit_hits,
            backoff,
            err,
        )

    # ── WebSocket auto-reconnect ────────────────────────────────────────

    _WS_RECONNECT_DELAYS = (30, 60, 120, 300, 600, 1800)  # seconds

    def _schedule_ws_reconnect(self) -> None:
        """Start the background reconnect task if not already running."""
        if self._ws_reconnect_task and not self._ws_reconnect_task.done():
            return
        self._ws_reconnect_task = self.hass.async_create_background_task(
            self._async_ws_reconnect_loop(),
            name=f"{self._config.coordinator_name}_ws_reconnect",
        )

    def _cancel_ws_reconnect(self) -> None:
        """Cancel any pending reconnect task."""
        if self._ws_reconnect_task and not self._ws_reconnect_task.done():
            self._ws_reconnect_task.cancel()
            self._ws_reconnect_task = None

    async def _async_ws_reconnect_loop(self) -> None:
        """Repeatedly attempt WebSocket reconnection with exponential backoff."""
        cfg = self._config
        for attempt, delay in enumerate(self._WS_RECONNECT_DELAYS, 1):
            await asyncio.sleep(delay)
            if self._ws_connected:
                return  # reconnected by a poll cycle
            _LOGGER.debug(
                "%s WebSocket reconnect attempt %d (after %ds)",
                cfg.api_label,
                attempt,
                delay,
            )
            devices = self.data
            if not devices:
                continue
            await self._async_start_websocket(devices)
            connected: bool = self._ws_connected
            if connected:
                _LOGGER.info(
                    "%s WebSocket reconnected after %d attempt(s)",
                    cfg.api_label,
                    attempt,
                )
                return
        _LOGGER.warning(
            "%s WebSocket reconnect failed after %d attempts, relying on polling",
            cfg.api_label,
            len(self._WS_RECONNECT_DELAYS),
        )

    # ── WebSocket watchdog ───────────────────────────────────────────────

    def _start_ws_watchdog(self) -> None:
        """Start a periodic check that the WebSocket is still receiving data."""
        self._stop_ws_watchdog()
        self._ws_watchdog_unsub = async_track_time_interval(
            self.hass,
            self._async_ws_watchdog_check,
            WS_WATCHDOG_CHECK_INTERVAL,
        )

    def _stop_ws_watchdog(self) -> None:
        """Cancel the WebSocket watchdog timer."""
        if self._ws_watchdog_unsub:
            self._ws_watchdog_unsub()
            self._ws_watchdog_unsub = None

    async def _async_ws_watchdog_check(self, _now: Any = None) -> None:
        """Check if the WebSocket has received a message recently.

        If no message has been received for WS_WATCHDOG_TIMEOUT_SECONDS,
        consider the connection stale, disconnect, and trigger a reconnect.
        """
        if not self._ws_connected or not self._ws:
            return

        last_msg = self._ws.last_message_time
        if last_msg <= 0:
            return  # no messages received yet, still initializing

        silence = time.monotonic() - last_msg
        if silence < WS_WATCHDOG_TIMEOUT_SECONDS:
            return

        cfg = self._config
        _LOGGER.warning(
            "%s WebSocket watchdog: no message received for %.0fs, "
            "forcing disconnect and reconnect",
            cfg.api_label,
            silence,
        )
        # Force-close the stale WebSocket
        self._ws_connected = False
        self._stop_ws_watchdog()
        self.update_interval = self._custom_poll_interval or cfg.scan_interval
        try:
            await self._ws.async_disconnect()
        except Exception:
            _LOGGER.debug("Error disconnecting stale WebSocket, ignoring")
        self._ws = None

        # Trigger immediate data refresh + reconnect
        await self.async_request_refresh()

    # ── MQTT bridge ──────────────────────────────────────────────────────

    async def _async_start_mqtt_bridge(self) -> None:
        """Initialize and start the MQTT bridge if enabled in options."""
        opts = self.config_entry.options
        if not opts.get(OPT_MQTT_ENABLE, False):
            self._mqtt_bridge = False  # sentinel: checked, not enabled
            return

        from .mqtt_bridge import MqttBridge

        prefix = opts.get(OPT_MQTT_TOPIC_PREFIX, DEFAULT_MQTT_TOPIC_PREFIX)
        publish = opts.get(OPT_MQTT_PUBLISH_STATES, True)
        subscribe = opts.get(OPT_MQTT_SUBSCRIBE_COMMANDS, True)

        bridge = MqttBridge(
            self.hass,
            topic_prefix=prefix,
            publish_states=publish,
            subscribe_commands=subscribe,
        )
        started = await bridge.async_start(
            command_handler=self._async_handle_mqtt_command if subscribe else None,
        )
        self._mqtt_bridge = bridge if started else False

    async def _async_handle_mqtt_command(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle an inbound MQTT command (subclasses can override)."""
        _LOGGER.debug("MQTT command received for %s: %s (no handler)", device_id, payload)

    async def async_shutdown(self) -> None:
        """Disconnect the WebSocket, revoke token, and clean up resources."""
        self._cancel_ws_reconnect()
        self._stop_ws_watchdog()
        if self._mqtt_bridge and hasattr(self._mqtt_bridge, "async_stop"):
            await self._mqtt_bridge.async_stop()
        if self._ws:
            await self._ws.async_disconnect()
            self._ws = None
        self._ws_connected = False
        try:
            await self._auth.async_revoke_token()
        except Exception:
            _LOGGER.debug("Token revocation failed during shutdown")

    def check_command_throttle(self) -> None:
        """Raise only when the command token bucket is empty.

        Token-bucket model: the bucket holds up to COMMAND_BURST_CAPACITY
        tokens and refills at 1 token per MIN_COMMAND_INTERVAL_SECONDS. Each
        command consumes one token. This lets the user fire a small burst of
        commands back-to-back (e.g. opening two irrigation valves) without
        tripping the throttle, while still capping the steady-state rate to
        protect the API quota.
        """
        now = time.monotonic()
        elapsed = now - self._command_tokens_updated
        refill = elapsed / MIN_COMMAND_INTERVAL_SECONDS
        self._command_tokens = min(
            float(COMMAND_BURST_CAPACITY),
            self._command_tokens + refill,
        )
        self._command_tokens_updated = now
        if self._command_tokens < 1.0:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_throttled",
            )
        self._command_tokens -= 1.0
        self._last_command_time = now
