"""Tests for base_coordinator rate-limit fixes (WS URL caching, connect guard, backoff)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,  # type: ignore[no-redef]
    )

from custom_components.gardena_smart_system.const import DOMAIN

from .conftest import ENTRY_DATA, make_mock_device

_PATCH_CLIENT = "custom_components.gardena_smart_system.coordinator.GardenaClient"
_PATCH_AUTH = "custom_components.gardena_smart_system.coordinator.GardenaAuth"
_PATCH_WS = "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"


def _make_mock_devices() -> dict[str, MagicMock]:
    dev = make_mock_device()
    return {dev.device_id: dev}


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        title="My Garden",
    )


def _setup_mocks(mock_devices: dict[str, MagicMock]):
    """Patch API classes and return (mock_client, mock_auth, mock_ws) context manager."""
    mock_auth = AsyncMock()
    mock_auth.is_token_valid = True

    mock_client = AsyncMock()
    mock_client.async_get_devices = AsyncMock(return_value=mock_devices)
    mock_client.async_get_websocket_url = AsyncMock(return_value="wss://test")

    mock_ws = AsyncMock()
    mock_ws.async_connect = AsyncMock()
    mock_ws.async_disconnect = AsyncMock()
    mock_ws.last_message_time = 0

    return mock_client, mock_auth, mock_ws


class TestWsUrlCaching:
    """Fix 1: WebSocket URL is cached and reused while token is valid."""

    async def test_ws_url_cached_on_first_connect(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """After first successful WS connect, the URL should be cached."""
        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data
            assert coordinator._cached_ws_url == "wss://test"
            mock_client.async_get_websocket_url.assert_called_once()

    async def test_ws_url_reused_on_reconnect_with_valid_token(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """On reconnect with valid token, the cached URL is reused (no new API call)."""
        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data
            assert mock_client.async_get_websocket_url.call_count == 1

            # Simulate WS disconnect + reconnect attempt
            coordinator._ws_connected = False
            coordinator._ws = None
            await coordinator._async_start_websocket(devices)

            # URL should have been reused — no additional fetch
            assert mock_client.async_get_websocket_url.call_count == 1

    async def test_ws_url_refetched_when_token_expired(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """When the token is no longer valid, a fresh WS URL must be fetched."""
        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data
            assert mock_client.async_get_websocket_url.call_count == 1

            # Expire the token
            mock_auth.is_token_valid = False
            coordinator._ws_connected = False
            coordinator._ws = None

            mock_client.async_get_websocket_url.return_value = "wss://new-url"
            await coordinator._async_start_websocket(devices)

            assert mock_client.async_get_websocket_url.call_count == 2
            assert coordinator._cached_ws_url == "wss://new-url"

    async def test_ws_url_cache_invalidated_on_connect_failure(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """If WS connect fails with cached URL, the cache is cleared."""
        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data
            assert coordinator._cached_ws_url == "wss://test"

            # Simulate reconnect with failing connect
            coordinator._ws_connected = False
            coordinator._ws = None
            mock_ws.async_connect = AsyncMock(side_effect=aiohttp.ClientError("Connection refused"))

            with patch(_PATCH_WS, return_value=mock_ws):
                await coordinator._async_start_websocket(devices)

            assert coordinator._cached_ws_url is None

    async def test_ws_url_cache_invalidated_on_ws_error(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """When _on_ws_error is called, the cached URL is cleared."""
        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data
            assert coordinator._cached_ws_url == "wss://test"

            from aiogardenasmart.exceptions import GardenaConnectionError

            coordinator._on_ws_error(GardenaConnectionError("lost"))

            assert coordinator._cached_ws_url is None


class TestWsConnectGuard:
    """Fix 2: asyncio.Lock prevents parallel WS connect attempts."""

    async def test_parallel_connect_attempts_are_blocked(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """When a WS connect is in progress, a second call is skipped."""
        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        # Track how many times _async_start_websocket_locked is entered
        locked_call_count = 0
        connect_started = asyncio.Event()
        connect_release = asyncio.Event()

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data
            coordinator._ws_connected = False
            coordinator._ws = None
            coordinator._cached_ws_url = None

            original_locked = coordinator._async_start_websocket_locked

            async def slow_locked(devs):
                nonlocal locked_call_count
                locked_call_count += 1
                connect_started.set()
                await connect_release.wait()
                await original_locked(devs)

            coordinator._async_start_websocket_locked = slow_locked

            # Start first connect in background
            task1 = hass.async_create_task(coordinator._async_start_websocket(devices))
            await connect_started.wait()

            # Second connect should be skipped (lock is held)
            await coordinator._async_start_websocket(devices)

            # Only one call entered the locked method
            assert locked_call_count == 1

            # Release the first connect
            connect_release.set()
            await task1


class TestRateLimitBackoffFromAuth:
    """Fix 3: 429 from auth/token endpoint triggers coordinator backoff."""

    async def test_rate_limit_during_ws_url_fetch_triggers_backoff(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """A GardenaRateLimitError during WS URL fetch triggers exponential backoff."""
        from aiogardenasmart.exceptions import GardenaRateLimitError

        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data

            # Simulate reconnect where WS URL fetch hits rate limit
            coordinator._ws_connected = False
            coordinator._ws = None
            coordinator._cached_ws_url = None
            mock_client.async_get_websocket_url = AsyncMock(
                side_effect=GardenaRateLimitError("429 Too Many Requests")
            )

            await coordinator._async_start_websocket(devices)

            # Backoff should have been applied
            assert coordinator._rate_limit_hits == 1
            assert coordinator.update_interval == timedelta(minutes=5)

    async def test_multiple_rate_limits_increase_backoff_exponentially(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Successive rate-limit hits double the backoff interval."""
        from aiogardenasmart.exceptions import GardenaRateLimitError

        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data
            coordinator._ws_connected = False
            coordinator._ws = None
            coordinator._cached_ws_url = None
            mock_client.async_get_websocket_url = AsyncMock(
                side_effect=GardenaRateLimitError("429")
            )

            # Hit 1: 5 min
            await coordinator._async_start_websocket(devices)
            assert coordinator.update_interval == timedelta(minutes=5)

            # Hit 2: 10 min
            coordinator._cached_ws_url = None
            await coordinator._async_start_websocket(devices)
            assert coordinator.update_interval == timedelta(minutes=10)

            # Hit 3: 20 min
            coordinator._cached_ws_url = None
            await coordinator._async_start_websocket(devices)
            assert coordinator.update_interval == timedelta(minutes=20)

    async def test_backoff_capped_at_cooldown(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Backoff never exceeds RATE_LIMIT_COOLDOWN (1 hour)."""
        from aiogardenasmart.exceptions import GardenaRateLimitError

        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data
            coordinator._ws_connected = False
            coordinator._ws = None
            coordinator._cached_ws_url = None
            mock_client.async_get_websocket_url = AsyncMock(
                side_effect=GardenaRateLimitError("429")
            )

            # Simulate many hits. Reset the circuit breaker each iteration so
            # the backoff keeps escalating — this test isolates the cap logic
            # in _apply_rate_limit_backoff, not the WS circuit breaker.
            for _ in range(10):
                coordinator._cached_ws_url = None
                coordinator._ws_cooldown_until = 0.0
                coordinator._ws_consecutive_failures = 0
                await coordinator._async_start_websocket(devices)

            # Should be capped at 1 hour
            assert coordinator.update_interval == timedelta(hours=1)

    async def test_rate_limit_resets_only_after_stability_window(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Rate-limit counter holds until RATE_LIMIT_RESET_SUCCESS_THRESHOLD hits.

        A single successful poll after a backoff is NOT proof the API has
        recovered; without this guard a persistently blocked key produced a
        saw-tooth log of hundreds of warnings per day.
        """
        from custom_components.gardena_smart_system.const import (
            RATE_LIMIT_RESET_SUCCESS_THRESHOLD,
        )

        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data

            # Simulate being deep in the backoff ladder
            coordinator._rate_limit_hits = 5
            coordinator._rate_limit_consecutive_successes = 0
            coordinator.update_interval = timedelta(hours=1)

            # First N-1 successes: counter still non-zero
            for _ in range(RATE_LIMIT_RESET_SUCCESS_THRESHOLD - 1):
                await coordinator._async_update_data()
                assert coordinator._rate_limit_hits == 5

            # The Nth success clears the counter
            await coordinator._async_update_data()
            assert coordinator._rate_limit_hits == 0
            assert coordinator._rate_limit_consecutive_successes == 0

    async def test_rate_limit_success_counter_resets_on_new_429(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """A fresh 429 wipes progress toward the stability threshold."""
        from aiogardenasmart.exceptions import GardenaRateLimitError

        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data
            coordinator._rate_limit_hits = 3
            coordinator._rate_limit_consecutive_successes = 2

            # A new 429 should zero the success counter so the backoff does
            # not collapse on the next lucky success.
            mock_client.async_get_devices = AsyncMock(
                side_effect=GardenaRateLimitError("429")
            )
            with pytest.raises(Exception):
                await coordinator._async_update_data()

            assert coordinator._rate_limit_consecutive_successes == 0
            assert coordinator._rate_limit_hits == 4


class TestCustomPollIntervalWithWs:
    """Custom poll interval only applies to REST fallback, not WS mode."""

    async def test_ws_connected_uses_health_check_interval_not_custom(
        self,
        hass: HomeAssistant,
    ) -> None:
        """With WS connected, the 6h health check is used even if custom interval is set."""
        from custom_components.gardena_smart_system.const import (
            OPT_POLL_INTERVAL_MINUTES,
            SCAN_INTERVAL_WS_CONNECTED,
        )

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            title="My Garden",
            options={OPT_POLL_INTERVAL_MINUTES: 5},
        )

        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            entry.add_to_hass(hass)
            await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

            coordinator = entry.runtime_data
            assert coordinator._ws_connected is True
            # Should use 6h WS interval, NOT the 5-minute custom interval
            assert coordinator.update_interval == SCAN_INTERVAL_WS_CONNECTED

    async def test_ws_disconnected_uses_custom_interval(
        self,
        hass: HomeAssistant,
    ) -> None:
        """With WS disconnected, the custom poll interval is used."""
        from custom_components.gardena_smart_system.const import OPT_POLL_INTERVAL_MINUTES

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            title="My Garden",
            options={OPT_POLL_INTERVAL_MINUTES: 10},
        )

        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            entry.add_to_hass(hass)
            await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

            coordinator = entry.runtime_data
            # Simulate WS disconnect — prevent reconnect so we observe fallback
            coordinator._ws_connected = False
            coordinator.update_interval = timedelta(hours=1)  # from rate limit
            with patch.object(coordinator, "_async_start_websocket"):
                await coordinator._async_update_data()

            assert coordinator.update_interval == timedelta(minutes=10)


class TestWsHandshakeKillSwitch:
    """Fix 4: after N 4xx WS handshake rejections, suspend WS reconnects."""

    def _make_handshake_error(self, status: int) -> aiohttp.WSServerHandshakeError:
        """Build a WSServerHandshakeError that mimics the real 410 shape."""
        request_info = aiohttp.RequestInfo(
            url=MagicMock(),
            method="GET",
            headers=MagicMock(),
            real_url=MagicMock(),
        )
        return aiohttp.WSServerHandshakeError(
            request_info=request_info,
            history=(),
            status=status,
            message="Invalid response status",
        )

    async def test_handshake_denial_increments_counter(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """Each 4xx WS handshake error bumps the denial counter."""
        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data

            for expected in (1, 2, 3):
                coordinator._on_ws_error(self._make_handshake_error(410))
                assert coordinator._ws_handshake_denials == expected

    async def test_handshake_denial_activates_kill_switch_at_threshold(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """At WS_HANDSHAKE_DENIAL_THRESHOLD, the kill-switch cooldown engages."""
        from custom_components.gardena_smart_system.const import (
            WS_HANDSHAKE_DENIAL_THRESHOLD,
            WS_KILL_SWITCH_COOLDOWN,
        )

        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data

            for _ in range(WS_HANDSHAKE_DENIAL_THRESHOLD):
                coordinator._on_ws_error(self._make_handshake_error(410))

            import time as _time

            remaining = coordinator._ws_kill_switch_until - _time.monotonic()
            assert remaining > 0
            assert remaining <= WS_KILL_SWITCH_COOLDOWN.total_seconds()

    async def test_kill_switch_skips_ws_connect(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """An active kill-switch short-circuits _async_start_websocket."""
        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data
            coordinator._ws_connected = False
            coordinator._cached_ws_url = None
            mock_client.async_get_websocket_url.reset_mock()

            import time as _time

            coordinator._ws_kill_switch_until = _time.monotonic() + 3600

            await coordinator._async_start_websocket(devices)

            # No REST call for a new WS URL — the budget is protected.
            mock_client.async_get_websocket_url.assert_not_called()

    async def test_non_4xx_ws_error_does_not_count_as_denial(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """A generic connection error is not a handshake denial."""
        from aiogardenasmart.exceptions import GardenaConnectionError

        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data
            coordinator._on_ws_error(GardenaConnectionError("tcp reset"))

            assert coordinator._ws_handshake_denials == 0
            assert coordinator._ws_kill_switch_until == 0.0

    async def test_device_update_clears_denials(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
    ) -> None:
        """A real device update (proof of healthy stream) clears the kill-switch."""
        devices = _make_mock_devices()
        mock_client, mock_auth, mock_ws = _setup_mocks(devices)

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_WS, return_value=mock_ws),
        ):
            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = mock_config_entry.runtime_data

            # Pre-load the counters as if we were deep in denial territory.
            import time as _time

            coordinator._ws_handshake_denials = 7
            coordinator._ws_kill_switch_until = _time.monotonic() + 3600

            # Simulate an incoming device update
            dev = next(iter(devices.values()))
            coordinator._on_device_update(dev.device_id, dev)

            assert coordinator._ws_handshake_denials == 0
            assert coordinator._ws_kill_switch_until == 0.0
