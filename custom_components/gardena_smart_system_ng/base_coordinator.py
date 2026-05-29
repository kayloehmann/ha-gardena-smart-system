"""Shared base coordinator for Gardena Smart System and Automower integrations."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    API_BUDGET_MONTHLY,
    API_BUDGET_STOP_PERCENT,
    APPLICATION_BLOCKED_NO_SUCCESS_HOURS,
    APPLICATION_BLOCKED_RATE_LIMIT_THRESHOLD,
    BUDGET_SAVE_DELAY_SECONDS,
    COMMAND_BURST_CAPACITY,
    DEFAULT_MQTT_TOPIC_PREFIX,
    DOMAIN,
    MIN_COMMAND_INTERVAL_SECONDS,
    OPT_MQTT_ENABLE,
    OPT_MQTT_PUBLISH_STATES,
    OPT_MQTT_SUBSCRIBE_COMMANDS,
    OPT_MQTT_TOPIC_PREFIX,
    OPT_POLL_INTERVAL_MINUTES,
    RATE_LIMIT_RESET_SUCCESS_THRESHOLD,
    RATE_LIMIT_STATE_SAVE_DELAY_SECONDS,
    STORAGE_VERSION_API_BUDGET,
    STORAGE_VERSION_RATE_LIMIT_STATE,
    WS_HANDSHAKE_DENIAL_STATUSES,
    WS_HANDSHAKE_DENIAL_THRESHOLD,
    WS_KILL_SWITCH_COOLDOWN,
    WS_REPAIR_ISSUE_THRESHOLD,
    WS_MAX_SESSION_SECONDS,
    WS_WATCHDOG_CHECK_INTERVAL,
    WS_WATCHDOG_TIMEOUT_SECONDS,
)

if TYPE_CHECKING:
    from .mqtt_bridge import MqttBridge

_LOGGER = logging.getLogger(__name__)

MQTT_RETRY_INTERVAL_SECONDS = 300


class ApiBudgetTracker:
    """Track the number of API requests made this calendar month.

    Uses Home Assistant's Store with delayed saves so that every increment
    does not trigger a disk write — at most one write per BUDGET_SAVE_DELAY_SECONDS.
    The counter resets automatically when a new calendar month starts.
    """

    def __init__(self, store: Store[dict[str, Any]], budget: int = API_BUDGET_MONTHLY) -> None:
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

    def _check_month_rollover(self) -> None:
        """Reset the counter if the calendar month has changed since load."""
        current_month = dt_util.now().strftime("%Y-%m")
        if current_month != self._month:
            self._month = current_month
            self._count = 0

    def increment(self, count: int = 1) -> None:
        """Record that *count* API requests were made.

        Automatically resets if the calendar month has changed since the last
        call. Schedules a delayed save so that rapid increments do not cause
        excessive I/O.
        """
        self._check_month_rollover()
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
        """Remaining budget as a percentage (0.0 - 100.0)."""
        self._check_month_rollover()
        return max(0.0, (1 - self._count / self._budget) * 100)

    @property
    def is_exhausted(self) -> bool:
        """True when less than API_BUDGET_STOP_PERCENT of the budget remains.

        Triggers the auto-stop safety net: while exhausted, the coordinator
        refuses polls, WS fetches, and user commands until the calendar month
        rolls over (or the user wires up a fresh Husqvarna application).
        """
        self._check_month_rollover()
        return self.remaining_percent < API_BUDGET_STOP_PERCENT

    async def async_reset(self) -> None:
        """Zero the counter and persist immediately.

        Intended for use when the user rotates to a fresh Husqvarna
        Application (new client_id) — the server-side quota is fresh, so the
        local mirror must be cleared too, otherwise `is_exhausted` would
        still fire and the `hub_api_budget_remaining` sensor would lie until
        the next calendar-month rollover.
        """
        self._month = dt_util.now().strftime("%Y-%m")
        self._count = 0
        await self._store.async_save({"month": self._month, "request_count": 0})


async def async_reset_api_budget_store(hass: HomeAssistant, entry_id: str) -> None:
    """Reset the persisted API-budget counter for a config entry.

    Called from the config-flow's reauth/reconfigure steps when the user
    supplies a new client_id. Safe to call even before the coordinator has
    been instantiated — it writes directly to the backing Store.
    """
    store: Store[dict[str, Any]] = Store(
        hass, STORAGE_VERSION_API_BUDGET, f"{DOMAIN}.{entry_id}.api_budget"
    )
    await store.async_save({"month": dt_util.now().strftime("%Y-%m"), "request_count": 0})


def _parse_iso_utc(value: str | None) -> datetime | None:
    """Parse a stored ISO datetime; return None on missing/invalid input.

    The Store roundtrips JSON, so we encode wall-clock timestamps as ISO
    strings.  A malformed value (manual edit, partial write, version skew
    between releases) must not crash the coordinator on load — fall back to
    None and let the caller treat it as "no record yet".
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        _LOGGER.debug("Discarding malformed timestamp from store: %r", value)
        return None


class RateLimitState:
    """Persist rate-limit and WebSocket-handshake-denial state across restarts.

    `_rate_limit_hits`, `_ws_handshake_denials`, and `_ws_kill_switch_until`
    were previously in-memory only.  Two real-world scenarios silently broke
    the kill-switch:

    1. **Setup-retry storm.**  When the coordinator's first refresh raises
       `UpdateFailed`, HA wraps it as `ConfigEntryNotReady` and tears the
       coordinator down, rebuilding it on the next retry tick.  Every retry
       therefore started the counters from zero, so the kill-switch never
       crossed its 5-denial threshold no matter how long the API stayed
       blocked — and each retry burned another REST call against the
       monthly quota.

    2. **HA restart mid-incident.**  Same shape, just at a different
       trigger.

    Persisting the state on disk and consulting it before any API call is
    made closes both holes.  All durations use wall-clock time
    (`dt_util.utcnow()`) — `time.monotonic()` resets on every process
    start, so a "1-hour cooldown" stored as a monotonic offset would
    expire the moment HA reboots.

    The per-process WS-reconnect ladder (15/30/60 min) deliberately stays
    on monotonic time: it is a transient back-pressure signal that should
    NOT survive a restart — a fresh process gets a fresh chance to
    connect.
    """

    def __init__(self, store: Store[dict[str, Any]]) -> None:
        self._store = store
        self._rate_limit_hits: int = 0
        self._last_429_at: datetime | None = None
        self._ws_handshake_denials: int = 0
        self._kill_switch_until: datetime | None = None
        self._last_success_at: datetime | None = None
        self._loaded = False

    async def async_load(self) -> None:
        """Load persisted state from disk (idempotent)."""
        data = await self._store.async_load() or {}
        self._rate_limit_hits = int(data.get("rate_limit_hits", 0) or 0)
        self._last_429_at = _parse_iso_utc(data.get("last_429_at"))
        self._ws_handshake_denials = int(data.get("ws_handshake_denials", 0) or 0)
        self._kill_switch_until = _parse_iso_utc(data.get("kill_switch_until"))
        self._last_success_at = _parse_iso_utc(data.get("last_success_at"))
        self._loaded = True

    def _schedule_save(self) -> None:
        """Persist current state, debounced.

        Each event (a 429, a denial, a success) triggers a save — using the
        delayed-save helper means a burst of events coalesces into a single
        write rather than thrashing disk.
        """
        self._store.async_delay_save(self._snapshot, delay=RATE_LIMIT_STATE_SAVE_DELAY_SECONDS)

    def _snapshot(self) -> dict[str, Any]:
        """Build the dict written to disk."""
        return {
            "rate_limit_hits": self._rate_limit_hits,
            "last_429_at": self._last_429_at.isoformat() if self._last_429_at else None,
            "ws_handshake_denials": self._ws_handshake_denials,
            "kill_switch_until": (
                self._kill_switch_until.isoformat() if self._kill_switch_until else None
            ),
            "last_success_at": (
                self._last_success_at.isoformat() if self._last_success_at else None
            ),
        }

    # ── Rate-limit ladder ──────────────────────────────────────────

    @property
    def rate_limit_hits(self) -> int:
        """Number of consecutive 429s observed (not yet cleared by successes)."""
        return self._rate_limit_hits

    @property
    def last_429_at(self) -> datetime | None:
        """Wall-clock UTC timestamp of the most recent 429."""
        return self._last_429_at

    def record_rate_limit(self) -> int:
        """Record a 429. Return the new total."""
        self._rate_limit_hits += 1
        self._last_429_at = dt_util.utcnow()
        self._schedule_save()
        return self._rate_limit_hits

    def reset_rate_limits(self) -> None:
        """Clear the rate-limit counter (the API is healthy again)."""
        if self._rate_limit_hits == 0 and self._last_429_at is None:
            return
        self._rate_limit_hits = 0
        self._last_429_at = None
        self._schedule_save()

    # ── WebSocket handshake denials & kill-switch ──────────────────

    @property
    def ws_handshake_denials(self) -> int:
        """Consecutive HTTP 4xx WebSocket handshake denials."""
        return self._ws_handshake_denials

    def record_handshake_denial(self) -> int:
        """Record one 4xx handshake denial. Return the new total."""
        self._ws_handshake_denials += 1
        self._schedule_save()
        return self._ws_handshake_denials

    def clear_handshake_denials(self) -> None:
        """Reset denial counter and kill-switch (a real WS update arrived)."""
        if self._ws_handshake_denials == 0 and self._kill_switch_until is None:
            return
        self._ws_handshake_denials = 0
        self._kill_switch_until = None
        self._schedule_save()

    def activate_kill_switch(self, duration: timedelta) -> None:
        """Engage the kill-switch for `duration` (wall-clock)."""
        self._kill_switch_until = dt_util.utcnow() + duration
        self._schedule_save()

    @property
    def kill_switch_until(self) -> datetime | None:
        """Wall-clock UTC timestamp when the kill-switch expires (None = inactive)."""
        return self._kill_switch_until

    def kill_switch_remaining(self) -> timedelta | None:
        """Time remaining on the kill-switch, or None if inactive/expired."""
        if self._kill_switch_until is None:
            return None
        remaining = self._kill_switch_until - dt_util.utcnow()
        if remaining.total_seconds() <= 0:
            return None
        return remaining

    def is_kill_switch_active(self) -> bool:
        """True iff the persisted kill-switch is still in the future."""
        return self.kill_switch_remaining() is not None

    # ── Successful poll tracking ───────────────────────────────────

    @property
    def last_success_at(self) -> datetime | None:
        """Wall-clock UTC timestamp of the last successful poll, if any."""
        return self._last_success_at

    def record_success(self) -> None:
        """Record that an API call succeeded just now."""
        self._last_success_at = dt_util.utcnow()
        self._schedule_save()

    def is_application_block_suspected(self) -> bool:
        """Heuristic: does the persisted state look like a server-side block?

        True when the rate-limit ladder has fired many times in a row AND no
        successful poll has been observed for the no-success window.  At
        that point client-side backoff has stopped helping and the user
        needs to rotate the Husqvarna Application.
        """
        if self._rate_limit_hits < APPLICATION_BLOCKED_RATE_LIMIT_THRESHOLD:
            return False
        if self._last_success_at is None:
            # Counter is high but we have no success record at all — treat as
            # blocked. Without this branch a freshly installed integration
            # whose first calls all 429 would never trigger the warning.
            return True
        elapsed = dt_util.utcnow() - self._last_success_at
        return elapsed >= timedelta(hours=APPLICATION_BLOCKED_NO_SUCCESS_HOURS)

    async def async_reset(self) -> None:
        """Wipe all state and persist immediately (e.g. after key rotation)."""
        self._rate_limit_hits = 0
        self._last_429_at = None
        self._ws_handshake_denials = 0
        self._kill_switch_until = None
        self._last_success_at = None
        await self._store.async_save(self._snapshot())


async def async_reset_rate_limit_state_store(hass: HomeAssistant, entry_id: str) -> None:
    """Wipe the persisted rate-limit state for a config entry.

    Mirrors `async_reset_api_budget_store` — call from reauth/reconfigure
    steps when the user supplies a new client_id, so the in-memory and on-
    disk state agree that the new Application starts from a clean slate.
    """
    store: Store[dict[str, Any]] = Store(
        hass, STORAGE_VERSION_RATE_LIMIT_STATE, f"{DOMAIN}.{entry_id}.rate_limit_state"
    )
    await store.async_save(
        {
            "rate_limit_hits": 0,
            "last_429_at": None,
            "ws_handshake_denials": 0,
            "kill_switch_until": None,
            "last_success_at": None,
        }
    )


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
    app_blocked_issue_key: str
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
        # Monotonic timestamp of the last WebSocket-pushed update, per device.
        # Used by command confirmation to distinguish a *fresh* push that
        # advanced the state from a stale cached state left over from a
        # previous cycle. Reset on process restart is fine — a command in
        # flight does not survive a restart anyway.
        self._ws_push_at: dict[str, float] = {}
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
        # Count consecutive successful polls so the rate-limit backoff only
        # resets after the API has been stable for a while. A single successful
        # poll after an hour-long cooldown does not mean the server is happy
        # again.  Stays in-memory: a fresh process is allowed to start
        # counting from zero, the persisted `rate_limit_hits` is what really
        # gates the backoff.
        self._rate_limit_consecutive_successes: int = 0
        self._ws_reconnect_task: asyncio.Task[None] | None = None
        self._mqtt_bridge: MqttBridge | None = None
        # Throttle for bridge start retries: HA may load the MQTT integration
        # after Gardena, so the first start attempt can legitimately fail.
        # Retry on the next poll, but at most once per MQTT_RETRY_INTERVAL to
        # avoid log spam when MQTT is permanently unavailable.
        self._mqtt_bridge_next_check: float = 0.0
        self._ws_watchdog_unsub: CALLBACK_TYPE | None = None
        self._ws_session_timer_unsub: CALLBACK_TYPE | None = None
        self._ws_connect_lock = asyncio.Lock()
        # WebSocket circuit breaker: consecutive failures trigger an escalating
        # cooldown during which no new WS connection attempts are made. Protects
        # the API rate-limit budget when WS URLs are repeatedly rejected
        # (observed as HTTP 410 on signed single-use URLs).
        # Deliberately monotonic + in-memory — these are short transient
        # back-pressure signals (15/30/60 min). Persisting them across an
        # HA restart would punish the user for a process bounce.
        self._ws_consecutive_failures: int = 0
        self._ws_cooldown_until: float = 0.0
        self._api_budget = ApiBudgetTracker(
            Store(hass, STORAGE_VERSION_API_BUDGET, f"{DOMAIN}.{entry.entry_id}.api_budget"),
        )
        # Kill-switch + rate-limit ladder are persisted: see RateLimitState
        # docstring for why in-memory was insufficient.
        self._rate_limit_state = RateLimitState(
            Store(
                hass,
                STORAGE_VERSION_RATE_LIMIT_STATE,
                f"{DOMAIN}.{entry.entry_id}.rate_limit_state",
            ),
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

    def ws_push_at(self, device_id: str) -> float:
        """Monotonic timestamp of the last WebSocket push for ``device_id``.

        Returns 0.0 if no push has ever been observed for this device. Callers
        compare a marker captured *before* sending a command against this value
        to tell a fresh confirming push apart from stale cached state.
        """
        return self._ws_push_at.get(device_id, 0.0)

    @property
    def api_budget(self) -> ApiBudgetTracker:
        """Return the API budget tracker."""
        return self._api_budget

    @property
    def rate_limit_state(self) -> RateLimitState:
        """Persisted rate-limit and WS-handshake-denial state."""
        return self._rate_limit_state

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
        if self._api_budget.is_exhausted:
            raise UpdateFailed(
                f"{cfg.api_label} API monthly budget nearly exhausted "
                f"({self._api_budget.request_count}/{self._api_budget.budget} requests "
                f"used this month); polling paused until the next calendar month"
            )
        # Kill-switch skip: when the WS handshake has been denied persistently
        # (HTTP 410/403/429), the Husqvarna Application is server-side blocked
        # and REST polling will hit the same 429. Burning the quota does not
        # help — hold off until the cooldown expires (and re-auth has happened,
        # which clears the kill-switch via _on_device_update).
        # The kill-switch state is persisted, so this branch fires correctly
        # even on the very first refresh after HA restart or a setup retry —
        # the previous in-memory-only check started every fresh coordinator
        # with `until = 0` and missed the persistent block entirely.
        remaining = self._rate_limit_state.kill_switch_remaining()
        if remaining is not None:
            if self.update_interval != remaining:
                self.update_interval = remaining
            _LOGGER.debug(
                "%s WebSocket kill-switch active for %.0f more min, skipping poll",
                cfg.api_label,
                remaining.total_seconds() / 60,
            )
            return self.data or {}
        # Count the request before it is sent — the server-side quota counts
        # every attempt, including the ones that fail. An optimistic increment
        # after success would slowly drift the local counter below the true
        # usage and let auto-stop fire too late.
        self._api_budget.increment()
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

        # The poll succeeded — record it for the application-block detector,
        # which uses (rate_limit_hits, last_success_at) to decide whether the
        # situation looks recoverable.
        self._rate_limit_state.record_success()
        # Rate-limit reset: only clear the backoff ladder after
        # RATE_LIMIT_RESET_SUCCESS_THRESHOLD consecutive successful polls. A
        # single success right after a 60-min cooldown is not proof that the
        # API has recovered, and eagerly resetting produced a saw-tooth
        # pattern (see GH issue: 478 rate-limit warnings / 12 h).
        # Custom poll interval only applies to REST fallback — when WebSocket
        # is active, data arrives via push and only a 6-hour health check is
        # needed.  Using a short custom interval with WS connected would burn
        # through the API rate limit budget for no benefit.
        if self._rate_limit_state.rate_limit_hits > 0:
            self._rate_limit_consecutive_successes += 1
            if self._rate_limit_consecutive_successes >= RATE_LIMIT_RESET_SUCCESS_THRESHOLD:
                _LOGGER.info(
                    "%s API stable after %d consecutive successes, clearing rate-limit backoff",
                    cfg.api_label,
                    self._rate_limit_consecutive_successes,
                )
                self._rate_limit_state.reset_rate_limits()
                self._rate_limit_consecutive_successes = 0
                # If the application-block Repair issue was raised because of
                # this run of 429s, the API recovering is the all-clear.
                ir.async_delete_issue(self.hass, DOMAIN, cfg.app_blocked_issue_key)
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

        # Start the MQTT bridge on first successful fetch, and retry if it
        # failed previously — HA may load the MQTT integration *after* Gardena,
        # so a first-poll failure is expected in that case.
        if self._mqtt_bridge is None or not self._mqtt_bridge.is_active:
            now = time.monotonic()
            if now >= self._mqtt_bridge_next_check:
                await self._async_start_mqtt_bridge()
                if self._mqtt_bridge is None or not self._mqtt_bridge.is_active:
                    self._mqtt_bridge_next_check = now + MQTT_RETRY_INTERVAL_SECONDS
        if self._mqtt_bridge is not None and self._mqtt_bridge.is_active:
            self.hass.async_create_task(
                self._mqtt_bridge.async_publish_all_devices(devices),
                name=f"{self._config.coordinator_name}_mqtt_publish_all",
            )

        # Remove devices that disappeared from the API (stale-devices rule)
        self._async_remove_stale_devices(devices)

        return devices

    _STALE_THRESHOLD = 3

    def _async_remove_stale_devices(self, fresh_devices: dict[str, DeviceT]) -> None:
        """Remove HA device registry entries for devices no longer in the API response.

        Devices must be absent for _STALE_THRESHOLD consecutive polls before removal.
        """
        if not self.data:
            return

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

    # Circuit-breaker cooldown schedule: (consecutive-failure threshold, seconds).
    # Once a threshold is crossed, no new WS connection is attempted for that
    # duration. A successful connection resets the counter.
    _WS_COOLDOWN_SCHEDULE: tuple[tuple[int, int], ...] = (
        (3, 15 * 60),
        (5, 30 * 60),
        (7, 60 * 60),
    )

    def _record_ws_failure(self) -> None:
        """Increment the WS failure counter and activate cooldown if crossed."""
        self._ws_consecutive_failures += 1
        n = self._ws_consecutive_failures
        cooldown_seconds = 0
        for threshold, seconds in self._WS_COOLDOWN_SCHEDULE:
            if n >= threshold:
                cooldown_seconds = seconds
        if cooldown_seconds > 0:
            self._ws_cooldown_until = time.monotonic() + cooldown_seconds
            _LOGGER.warning(
                "%s WebSocket failed %d times consecutively, cooling down for %d min "
                "before retrying (protecting API rate-limit budget); REST polling "
                "continues",
                self._config.api_label,
                n,
                cooldown_seconds // 60,
            )

    def _reset_ws_failures(self) -> None:
        """Clear the WS failure counter and cooldown after a successful connect.

        Does NOT reset the handshake-denial kill-switch — that survives until
        a real device update arrives (_on_device_update), because
        ws_connect() returning synchronously is not proof the handshake
        succeeded: the listen task may still fail milliseconds later with a
        WSServerHandshakeError.
        """
        if self._ws_consecutive_failures:
            _LOGGER.debug(
                "%s WebSocket connected — resetting failure counter (was %d)",
                self._config.api_label,
                self._ws_consecutive_failures,
            )
        self._ws_consecutive_failures = 0
        self._ws_cooldown_until = 0.0

    def _clear_ws_handshake_denials(self) -> None:
        """Clear the handshake-denial kill-switch after a real device update."""
        cfg = self._config
        denials = self._rate_limit_state.ws_handshake_denials
        if denials:
            _LOGGER.debug(
                "%s WebSocket stream healthy — clearing %d handshake denial(s)",
                cfg.api_label,
                denials,
            )
        self._rate_limit_state.clear_handshake_denials()
        ir.async_delete_issue(self.hass, DOMAIN, cfg.app_blocked_issue_key)

    async def _async_start_websocket(self, devices: dict[str, DeviceT]) -> None:
        """Start the WebSocket for real-time updates.

        Protected by a lock to prevent parallel connect attempts (e.g. watchdog +
        poll cycle racing).  The WebSocket URL is cached and reused as long as
        the auth token is still valid; a fresh URL is fetched only when the token
        was refreshed or the cached URL fails to connect.
        """
        if self._api_budget.is_exhausted:
            _LOGGER.debug(
                "%s API budget exhausted — skipping WebSocket connect",
                self._config.api_label,
            )
            return

        now = time.monotonic()
        if now < self._ws_cooldown_until:
            _LOGGER.debug(
                "%s WebSocket in cooldown for %.0fs, skipping connect",
                self._config.api_label,
                self._ws_cooldown_until - now,
            )
            return

        ks_remaining = self._rate_limit_state.kill_switch_remaining()
        if ks_remaining is not None:
            _LOGGER.debug(
                "%s WebSocket kill-switch active for %.0f more min, skipping connect",
                self._config.api_label,
                ks_remaining.total_seconds() / 60,
            )
            return

        if self._ws_connect_lock.locked():
            _LOGGER.debug(
                "%s WebSocket connect already in progress, skipping",
                self._config.api_label,
            )
            return

        async with self._ws_connect_lock:
            # Double-check under the lock: a prior caller may have completed
            # the connect between our locked() check and lock acquisition.
            if self._ws_connected:
                return
            await self._async_start_websocket_locked(devices)

    async def _async_start_websocket_locked(self, devices: dict[str, DeviceT]) -> None:
        """Inner WebSocket start logic (must be called under _ws_connect_lock)."""
        cfg = self._config

        # Always fetch a fresh WS URL. Gardena signs URLs as single-use; once
        # one has been handed to ws_connect the server consumes it, and the
        # next handshake against the same URL returns 410 Gone (#18, second
        # wave: each watchdog-driven reconnect burned one cycle on a stale
        # URL before recovering).
        if self._ws_url_is_api_call:
            # Increment before the call — failed attempts still count
            # against the server-side monthly quota (see note in
            # _async_update_data).
            self._api_budget.increment()
        try:
            ws_url = await self._async_get_ws_url(devices)
        except cfg.rate_limit_error_type as err:
            self._apply_rate_limit_backoff(err)
            self._record_ws_failure()
            return
        except cfg.auth_error_type as err:
            _LOGGER.warning(
                "Could not obtain %s WebSocket URL (auth), will rely on polling: %s",
                cfg.api_label,
                err,
            )
            return
        except cfg.connection_error_type as err:
            _LOGGER.warning(
                "Could not obtain %s WebSocket URL, will rely on polling: %s",
                cfg.api_label,
                err,
            )
            self._record_ws_failure()
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
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            _LOGGER.warning(
                "Could not connect %s WebSocket, will rely on polling: %s",
                cfg.api_label,
                err,
            )
            self._ws = None
            self._record_ws_failure()
            self._record_ws_handshake_denial(err)
            return

        self._ws_connected = True
        self._reset_ws_failures()
        self._cancel_ws_reconnect()
        self._start_ws_watchdog()
        self._start_ws_session_timer()
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
        # A real device update is the earliest reliable proof that the WS
        # stream is actually working — not just that ws_connect() returned
        # synchronously. Clear the handshake-denial kill-switch here.
        if self._rate_limit_state.ws_handshake_denials:
            self._clear_ws_handshake_denials()
        if self.data is not None:
            self.data[device_id] = device
        self._ws_push_at[device_id] = time.monotonic()
        if self._mqtt_bridge is not None and self._mqtt_bridge.is_active:
            self.hass.async_create_task(
                self._mqtt_bridge.async_publish_device_state(device_id, device),
                name=f"{self._config.coordinator_name}_mqtt_publish_device",
            )
        self.async_set_updated_data(self.data or {})

    def _on_ws_error(self, err: Exception) -> None:
        """Called when the WebSocket connection fails unrecoverably."""
        cfg = self._config
        # The same WS-lost event used to produce three log lines — an ERROR
        # here, a WARN from `aiogardenasmart.websocket`, and another WARN
        # below. Three lines per drop multiplied by an over-aggressive
        # watchdog meant the log was flooded for users whose WS was actually
        # fine (#18). The library line is now DEBUG; the user-facing line
        # below adapts severity to "is this transient or persistent?".
        self._ws_connected = False
        self._ws = None
        self._stop_ws_watchdog()
        self._stop_ws_session_timer()
        self.update_interval = self._custom_poll_interval or cfg.scan_interval

        if isinstance(err, cfg.auth_error_type):
            # Auth failures are resolved by re-auth, not by cooling down.
            self.config_entry.async_start_reauth(self.hass)
            return

        self._record_ws_failure()
        self._record_ws_handshake_denial(err)

        # Only surface the milder WS-lost repair notification once the WS has
        # failed WS_REPAIR_ISSUE_THRESHOLD times in a row. A single transient
        # drop auto-reconnects in seconds and should not be user-visible (see
        # issue #17). The kill-switch path creates a more severe
        # husqvarna_application_blocked issue instead (in
        # _record_ws_handshake_denial), so we skip this one when kill-switch
        # is active to avoid stacking two issues for the same root cause.
        kill_switch_active = self._rate_limit_state.is_kill_switch_active()
        persistent_failure = self._ws_consecutive_failures >= WS_REPAIR_ISSUE_THRESHOLD
        if persistent_failure and not kill_switch_active:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                cfg.ws_issue_key,
                is_fixable=True,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="websocket_connection_failed",
            )
        # Severity follows persistence: a single drop that auto-reconnects
        # in 60 s is DEBUG noise, repeated drops escalate to WARN once the
        # repair-issue threshold is crossed (matching the user-visible
        # repair issue's appearance).
        log_level = logging.WARNING if persistent_failure else logging.DEBUG
        _LOGGER.log(
            log_level,
            "%s WebSocket connection lost, falling back to polling: %s",
            cfg.api_label,
            err,
        )
        # Only schedule reconnect if the kill-switch isn't active — otherwise
        # the loop would burn REST calls fetching WS URLs for attempts that
        # are all going to be skipped anyway.
        if self._rate_limit_state.is_kill_switch_active():
            return
        self._schedule_ws_reconnect()

    def _record_ws_handshake_denial(self, err: Exception) -> None:
        """Track HTTP 4xx rejections at the WS handshake and trigger kill-switch.

        4xx at handshake (typically 410 for signed-URL "Gone", 403 for
        forbidden, 429 for rate-limit at the gateway) consistently indicates
        a server-side denial that client retry logic cannot recover from.
        After WS_HANDSHAKE_DENIAL_THRESHOLD such events in a row we suspend
        the WS subsystem for WS_KILL_SWITCH_COOLDOWN and log a loud hint
        about key rotation.
        """
        status = getattr(err, "status", None)
        if status not in WS_HANDSHAKE_DENIAL_STATUSES:
            return
        cfg = self._config
        denials = self._rate_limit_state.record_handshake_denial()
        if denials < WS_HANDSHAKE_DENIAL_THRESHOLD:
            return
        self._rate_limit_state.activate_kill_switch(WS_KILL_SWITCH_COOLDOWN)
        _LOGGER.warning(
            "%s WebSocket handshake rejected %d times in a row (HTTP %s), "
            "suspending WS reconnect for %d min. This usually indicates the "
            "Husqvarna API key has been blocked — rotate the Application in "
            "the Developer Portal (https://developer.husqvarnagroup.cloud/) "
            "and re-authenticate the integration. REST polling is also paused "
            "during the cooldown to protect the API budget.",
            cfg.api_label,
            denials,
            status,
            int(WS_KILL_SWITCH_COOLDOWN.total_seconds()) // 60,
        )
        # The milder ws_connection_failed issue would be redundant next to the
        # app-blocked one (same root cause, stronger call to action).
        self._raise_application_blocked_issue()

    def _apply_rate_limit_backoff(self, err: Exception) -> None:
        """Apply exponential backoff for a rate-limit error.

        Shared between the poll cycle (_async_update_data) and WebSocket URL
        fetching so that a 429 from the auth token endpoint triggers the same
        backoff as a 429 from a normal API call.
        """
        cfg = self._config
        hits = self._rate_limit_state.record_rate_limit()
        # A fresh 429 invalidates any prior run of stability — the counter
        # towards RATE_LIMIT_RESET_SUCCESS_THRESHOLD restarts from zero.
        self._rate_limit_consecutive_successes = 0
        backoff = min(
            cfg.rate_limit_cooldown,
            timedelta(minutes=5) * (2 ** (hits - 1)),
        )
        self.update_interval = backoff
        _LOGGER.warning(
            "Rate limited by %s API (hit #%d), backing off to %s: %s",
            cfg.api_label,
            hits,
            backoff,
            err,
        )
        # When the rate-limit ladder has fired this many times AND no poll
        # has succeeded for the no-success window, we are no longer in a
        # transient slowdown — the Application is almost certainly server-
        # side blocked. Surface the existing repair issue so the user knows
        # to rotate the Application; client-side retries cannot help here.
        if self._rate_limit_state.is_application_block_suspected():
            self._raise_application_blocked_issue()

    def _raise_application_blocked_issue(self) -> None:
        """Surface the 'rotate your Husqvarna Application' Repair issue.

        Idempotent — calling repeatedly is harmless because
        `ir.async_create_issue` deduplicates by domain+issue_id.
        """
        cfg = self._config
        ir.async_delete_issue(self.hass, DOMAIN, cfg.ws_issue_key)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            cfg.app_blocked_issue_key,
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="husqvarna_application_blocked",
            translation_placeholders={"api_label": cfg.api_label},
            learn_more_url="https://developer.husqvarnagroup.cloud/",
        )

    # ── WebSocket auto-reconnect ────────────────────────────────────────

    _WS_RECONNECT_DELAYS = (60, 300, 900)  # seconds

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
            now = time.monotonic()
            if now < self._ws_cooldown_until:
                _LOGGER.debug(
                    "%s WebSocket circuit breaker active, aborting reconnect loop",
                    cfg.api_label,
                )
                return
            if self._rate_limit_state.is_kill_switch_active():
                _LOGGER.debug(
                    "%s WebSocket kill-switch active, aborting reconnect loop",
                    cfg.api_label,
                )
                return
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
        except (aiohttp.ClientError, TimeoutError, OSError):
            # Stale WebSocket may have already dropped the TCP connection; all
            # we're doing is making sure the local handle is released.
            _LOGGER.debug("Error disconnecting stale WebSocket, ignoring")
        self._ws = None

        # The regular coordinator loop will pick this up on its next tick and
        # trigger a REST poll + WS reconnect. Calling async_request_refresh()
        # here would double the API calls per watchdog event.
        self._schedule_ws_reconnect()


    # ── WebSocket session timer (2-hour server limit) ────────────────────

    def _start_ws_session_timer(self) -> None:
        """Schedule a proactive reconnect before the server-enforced 2-hour session limit."""
        self._stop_ws_session_timer()
        self._ws_session_timer_unsub = async_call_later(
            self.hass,
            WS_MAX_SESSION_SECONDS,
            self._async_ws_session_expired,
        )

    def _stop_ws_session_timer(self) -> None:
        """Cancel the pending session-expiry reconnect timer."""
        if self._ws_session_timer_unsub:
            self._ws_session_timer_unsub()
            self._ws_session_timer_unsub = None

    async def _async_ws_session_expired(self, _now: object = None) -> None:
        """Proactively reconnect before the 2-hour server-enforced session limit."""
        if not self._ws_connected or not self._ws:
            return
        cfg = self._config
        _LOGGER.debug(
            "%s WebSocket session limit approaching (%ds), proactively reconnecting",
            cfg.api_label,
            WS_MAX_SESSION_SECONDS,
        )
        self._ws_connected = False
        self._stop_ws_watchdog()
        self.update_interval = self._custom_poll_interval or cfg.scan_interval
        try:
            await self._ws.async_disconnect()
        except (aiohttp.ClientError, TimeoutError, OSError):
            _LOGGER.debug("Error disconnecting WebSocket for session renewal, ignoring")
        self._ws = None
        self._schedule_ws_reconnect()

    # ── MQTT bridge ──────────────────────────────────────────────────────

    async def _async_start_mqtt_bridge(self) -> None:
        """Initialize and start the MQTT bridge if enabled in options.

        Leaves ``self._mqtt_bridge`` at ``None`` when the bridge is disabled or
        its start fails (MQTT integration not yet loaded). The caller retries
        periodically via ``_mqtt_bridge_next_check``.
        """
        opts = self.config_entry.options
        if not opts.get(OPT_MQTT_ENABLE, False):
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
        if started:
            self._mqtt_bridge = bridge

    async def _async_handle_mqtt_command(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle an inbound MQTT command (subclasses can override)."""
        _LOGGER.debug("MQTT command received for %s: %s (no handler)", device_id, payload)

    async def async_shutdown(self) -> None:
        """Disconnect the WebSocket, revoke token, and clean up resources."""
        self._cancel_ws_reconnect()
        self._stop_ws_watchdog()
        self._stop_ws_session_timer()
        if self._mqtt_bridge is not None:
            await self._mqtt_bridge.async_stop()
        if self._ws:
            await self._ws.async_disconnect()
            self._ws = None
        self._ws_connected = False
        try:
            await self._auth.async_revoke_token()
        except (aiohttp.ClientError, TimeoutError, OSError):
            # Revocation is best-effort; if the network is already unreachable
            # during shutdown there is nothing actionable to do.
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
        if self._api_budget.is_exhausted:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="api_budget_exhausted",
            )
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
