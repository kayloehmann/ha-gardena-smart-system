"""Tests for the Gardena Smart System DataUpdateCoordinator."""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,  # type: ignore[no-redef]
    )

from custom_components.gardena_smart_system.const import (
    DOMAIN,
    RATE_LIMIT_COOLDOWN,
    SCAN_INTERVAL,
    SCAN_INTERVAL_WS_CONNECTED,
    WS_REPAIR_ISSUE_THRESHOLD,
)
from custom_components.gardena_smart_system.coordinator import GardenaCoordinator

from .conftest import ENTRY_DATA, make_mock_device

_PATCH_WS = "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a config entry added to hass."""
    e = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    e.add_to_hass(hass)
    return e


@pytest.fixture
def coordinator(hass: HomeAssistant, entry: MockConfigEntry) -> GardenaCoordinator:
    """Return a GardenaCoordinator with mocked session."""
    return GardenaCoordinator(hass, entry, MagicMock())


class TestAsyncUpdateData:
    async def test_returns_devices_from_api(self, coordinator: GardenaCoordinator) -> None:
        devices = {"dev-1": make_mock_device()}
        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(return_value=devices)

        with patch.object(coordinator, "_async_start_websocket", new_callable=AsyncMock):
            result = await coordinator._async_update_data()

        assert result == devices

    async def test_auth_error_raises_config_entry_auth_failed(
        self, coordinator: GardenaCoordinator
    ) -> None:
        from aiogardenasmart.exceptions import GardenaAuthenticationError

        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(
            side_effect=GardenaAuthenticationError("token expired")
        )

        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

    async def test_connection_error_raises_update_failed(
        self, coordinator: GardenaCoordinator
    ) -> None:
        from aiogardenasmart.exceptions import GardenaConnectionError

        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(
            side_effect=GardenaConnectionError("unreachable")
        )

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    async def test_websocket_started_on_first_successful_fetch(
        self, coordinator: GardenaCoordinator
    ) -> None:
        devices = {"dev-1": make_mock_device()}
        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(return_value=devices)

        with patch.object(
            coordinator, "_async_start_websocket", new_callable=AsyncMock
        ) as mock_start:
            await coordinator._async_update_data()

        mock_start.assert_called_once_with(devices)

    async def test_websocket_not_restarted_when_already_connected(
        self, coordinator: GardenaCoordinator
    ) -> None:
        devices = {"dev-1": make_mock_device()}
        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(return_value=devices)
        coordinator._ws_connected = True  # Already connected

        with patch.object(
            coordinator, "_async_start_websocket", new_callable=AsyncMock
        ) as mock_start:
            await coordinator._async_update_data()

        mock_start.assert_not_called()


class TestStartWebSocket:
    async def test_websocket_connected_on_success(self, coordinator: GardenaCoordinator) -> None:
        coordinator._client = AsyncMock()
        coordinator._client.async_get_websocket_url = AsyncMock(
            return_value="wss://gardena.example/ws"
        )

        with patch(_PATCH_WS) as mock_ws_cls:
            mock_ws = AsyncMock()
            mock_ws_cls.return_value = mock_ws
            await coordinator._async_start_websocket({})

        assert coordinator._ws_connected is True
        mock_ws.async_connect.assert_called_once_with("wss://gardena.example/ws")

    async def test_websocket_url_auth_error_logs_warning(
        self, coordinator: GardenaCoordinator
    ) -> None:
        from aiogardenasmart.exceptions import GardenaAuthenticationError

        coordinator._client = AsyncMock()
        coordinator._client.async_get_websocket_url = AsyncMock(
            side_effect=GardenaAuthenticationError("no ws access")
        )

        await coordinator._async_start_websocket({})

        assert coordinator._ws_connected is False

    async def test_websocket_connect_failure_falls_back_to_polling(
        self, coordinator: GardenaCoordinator
    ) -> None:
        """If async_connect raises, the coordinator falls back to polling."""
        coordinator._client = AsyncMock()
        coordinator._client.async_get_websocket_url = AsyncMock(
            return_value="wss://gardena.example/ws"
        )

        with patch(_PATCH_WS) as mock_ws_cls:
            mock_ws = AsyncMock()
            mock_ws.async_connect = AsyncMock(side_effect=OSError("Connection refused"))
            mock_ws_cls.return_value = mock_ws
            await coordinator._async_start_websocket({})

        assert coordinator._ws_connected is False
        assert coordinator._ws is None

    async def test_websocket_reconnect_clears_repair_issue(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        # Create the repair issue first — requires WS_REPAIR_ISSUE_THRESHOLD
        # failures in a row since v1.12.5 (issue #17).
        for _ in range(WS_REPAIR_ISSUE_THRESHOLD):
            coordinator._on_ws_error(RuntimeError("lost"))
            coordinator._cancel_ws_reconnect()

        issue_reg = ir.async_get(hass)
        assert issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed") is not None

        # Clear the circuit-breaker cooldown so _async_start_websocket proceeds
        # (3 failures engage the first cooldown step).
        coordinator._ws_cooldown_until = 0.0

        # Reconnect should clear it
        coordinator._client = AsyncMock()
        coordinator._client.async_get_websocket_url = AsyncMock(return_value="wss://test")
        with patch(_PATCH_WS) as mock_ws_cls:
            mock_ws_cls.return_value = AsyncMock()
            await coordinator._async_start_websocket({})

        assert issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed") is None


class TestOnDeviceUpdate:
    def test_device_update_replaces_device_in_data(self, coordinator: GardenaCoordinator) -> None:
        old_device = make_mock_device("dev-1", "SN001")
        coordinator.data = {"dev-1": old_device}

        new_device = make_mock_device("dev-1", "SN001", name="Updated")
        coordinator._on_device_update("dev-1", new_device)

        assert coordinator.data["dev-1"] is new_device

    def test_device_update_with_no_existing_data(self, coordinator: GardenaCoordinator) -> None:
        coordinator.data = None
        device = make_mock_device()
        # Should not raise
        coordinator._on_device_update("dev-1", device)


class TestStaleDevices:
    async def test_stale_device_removed_after_threshold(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        """Device is only removed after _STALE_THRESHOLD consecutive misses."""
        old_device = make_mock_device("old-dev", "SN-OLD")
        new_device = make_mock_device("new-dev", "SN-NEW")
        coordinator.data = {"old-dev": old_device}

        dev_reg = dr.async_get(hass)
        dev_reg.async_get_or_create(
            config_entry_id=coordinator.config_entry.entry_id,
            identifiers={(DOMAIN, "SN-OLD")},
        )

        # First two misses — device should NOT be removed yet
        # (fresh_devices is mutated by the method to keep the device)
        for _ in range(coordinator._STALE_THRESHOLD - 1):
            fresh = {"new-dev": new_device}
            coordinator._async_remove_stale_devices(fresh)
            # Method keeps old_device in fresh so coordinator.data retains it
            coordinator.data = fresh
            assert dev_reg.async_get_device(identifiers={(DOMAIN, "SN-OLD")}) is not None

        # Third miss — now it should be removed
        fresh = {"new-dev": new_device}
        coordinator._async_remove_stale_devices(fresh)
        coordinator.data = fresh
        assert dev_reg.async_get_device(identifiers={(DOMAIN, "SN-OLD")}) is None

    async def test_stale_counter_resets_when_device_reappears(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        """If a device reappears, its miss counter resets."""
        device = make_mock_device("dev-1", "SN001")
        coordinator.data = {"dev-1": device}

        dev_reg = dr.async_get(hass)
        dev_reg.async_get_or_create(
            config_entry_id=coordinator.config_entry.entry_id,
            identifiers={(DOMAIN, "SN001")},
        )

        # Miss once
        fresh: dict = {}
        coordinator._async_remove_stale_devices(fresh)
        coordinator.data = fresh  # Method keeps device in fresh
        assert coordinator._stale_miss_counts.get("dev-1") == 1

        # Reappear — counter should reset
        coordinator._async_remove_stale_devices({"dev-1": device})
        assert "dev-1" not in coordinator._stale_miss_counts

    async def test_no_removal_when_device_still_present(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        device = make_mock_device()
        coordinator.data = {device.device_id: device}

        dev_reg = dr.async_get(hass)
        dev_reg.async_get_or_create(
            config_entry_id=coordinator.config_entry.entry_id,
            identifiers={(DOMAIN, device.serial)},
        )

        coordinator._async_remove_stale_devices({device.device_id: device})

        assert dev_reg.async_get_device(identifiers={(DOMAIN, device.serial)}) is not None

    def test_no_op_on_first_poll_when_data_is_none(self, coordinator: GardenaCoordinator) -> None:
        coordinator.data = None
        # Should not raise
        coordinator._async_remove_stale_devices({})

    def test_device_without_serial_skipped(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        device = make_mock_device()
        device.serial = None  # No serial — skip registry removal
        coordinator.data = {device.device_id: device}

        # Exhaust threshold without removal (no serial)
        for _ in range(coordinator._STALE_THRESHOLD):
            coordinator._async_remove_stale_devices({})


class TestRepairIssues:
    def test_ws_error_creates_repair_issue_after_threshold(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        """Issue #17: repair issue only appears after N consecutive drops."""
        for _ in range(WS_REPAIR_ISSUE_THRESHOLD):
            coordinator._on_ws_error(RuntimeError("connection dropped"))
            coordinator._cancel_ws_reconnect()

        issue_reg = ir.async_get(hass)
        issue = issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed")
        assert issue is not None
        assert issue.severity == ir.IssueSeverity.WARNING
        assert issue.is_fixable

    def test_single_transient_ws_drop_does_not_create_repair_issue(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        """A single WS drop should not be user-visible (issue #17)."""
        coordinator._on_ws_error(RuntimeError("brief drop"))
        coordinator._cancel_ws_reconnect()

        issue_reg = ir.async_get(hass)
        assert issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed") is None

    def test_ws_error_sets_connected_false(self, coordinator: GardenaCoordinator) -> None:
        coordinator._ws_connected = True
        coordinator._on_ws_error(RuntimeError("dropped"))
        assert coordinator._ws_connected is False


class TestShutdown:
    async def test_shutdown_disconnects_websocket(self, coordinator: GardenaCoordinator) -> None:
        mock_ws = AsyncMock()
        mock_ws.async_disconnect = AsyncMock()
        coordinator._ws = mock_ws
        coordinator._ws_connected = True

        await coordinator.async_shutdown()

        mock_ws.async_disconnect.assert_called_once()
        assert coordinator._ws is None
        assert coordinator._ws_connected is False

    async def test_shutdown_with_no_websocket(self, coordinator: GardenaCoordinator) -> None:
        coordinator._ws = None
        # Should not raise
        await coordinator.async_shutdown()

    async def test_shutdown_token_revocation_failure_does_not_raise(
        self, coordinator: GardenaCoordinator
    ) -> None:
        coordinator._ws = None
        coordinator._auth.async_revoke_token = AsyncMock(
            side_effect=aiohttp.ClientError("network down")
        )
        # Should not raise
        await coordinator.async_shutdown()


class TestRateLimitBackoff:
    """Test rate limit handling in _async_update_data."""

    async def test_rate_limit_raises_update_failed(self, coordinator: GardenaCoordinator) -> None:
        from aiogardenasmart.exceptions import GardenaRateLimitError

        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(side_effect=GardenaRateLimitError("429"))

        with pytest.raises(UpdateFailed, match="Rate limited"):
            await coordinator._async_update_data()

    async def test_rate_limit_increases_poll_interval(
        self, coordinator: GardenaCoordinator
    ) -> None:
        from aiogardenasmart.exceptions import GardenaRateLimitError

        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(side_effect=GardenaRateLimitError("429"))

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        # First hit: graduated backoff starts at 5 minutes
        assert coordinator.update_interval == timedelta(minutes=5)

    async def test_successful_fetch_restores_normal_interval(
        self, coordinator: GardenaCoordinator
    ) -> None:
        """After a rate limit, a successful fetch restores the normal interval."""
        coordinator.update_interval = RATE_LIMIT_COOLDOWN
        devices = {"dev-1": make_mock_device()}
        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(return_value=devices)

        with patch.object(coordinator, "_async_start_websocket", new_callable=AsyncMock):
            await coordinator._async_update_data()

        assert coordinator.update_interval == SCAN_INTERVAL

    async def test_successful_fetch_restores_ws_interval_when_connected(
        self, coordinator: GardenaCoordinator
    ) -> None:
        """After a rate limit with WS connected, restore the longer WS interval."""
        coordinator.update_interval = RATE_LIMIT_COOLDOWN
        coordinator._ws_connected = True
        devices = {"dev-1": make_mock_device()}
        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(return_value=devices)

        await coordinator._async_update_data()

        assert coordinator.update_interval == SCAN_INTERVAL_WS_CONNECTED

    async def test_consecutive_rate_limits_escalate_backoff(
        self, coordinator: GardenaCoordinator
    ) -> None:
        from aiogardenasmart.exceptions import GardenaRateLimitError

        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(side_effect=GardenaRateLimitError("429"))

        expected = [timedelta(minutes=5), timedelta(minutes=10), timedelta(minutes=20)]
        for i in range(3):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()
            assert coordinator.update_interval == expected[i]

    async def test_backoff_caps_at_rate_limit_cooldown(
        self, coordinator: GardenaCoordinator
    ) -> None:
        """Graduated backoff never exceeds the configured rate_limit_cooldown."""
        from aiogardenasmart.exceptions import GardenaRateLimitError

        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(side_effect=GardenaRateLimitError("429"))

        # Hit 7 times — 5, 10, 20, 40, 60, 60, 60
        for _ in range(7):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

        assert coordinator.update_interval == RATE_LIMIT_COOLDOWN

    async def test_successful_fetch_resets_backoff_counter(
        self, coordinator: GardenaCoordinator
    ) -> None:
        """After N consecutive successes the ladder restarts at 5 min.

        A single success after a long cooldown is no longer proof of
        recovery — the counter only clears after
        RATE_LIMIT_RESET_SUCCESS_THRESHOLD successful polls.
        """
        from aiogardenasmart.exceptions import GardenaRateLimitError

        from custom_components.gardena_smart_system.const import (
            RATE_LIMIT_RESET_SUCCESS_THRESHOLD,
        )

        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(side_effect=GardenaRateLimitError("429"))

        # Two rate-limit hits (5min, 10min)
        for _ in range(2):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()
        assert coordinator.update_interval == timedelta(minutes=10)

        # N successful fetches required to clear the backoff ladder.
        devices = {"dev-1": MagicMock()}
        coordinator._client.async_get_devices = AsyncMock(return_value=devices)
        with patch.object(coordinator, "_async_start_websocket", new_callable=AsyncMock):
            for _ in range(RATE_LIMIT_RESET_SUCCESS_THRESHOLD):
                await coordinator._async_update_data()

        # Next rate limit starts at 5min again
        coordinator._client.async_get_devices = AsyncMock(side_effect=GardenaRateLimitError("429"))
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        assert coordinator.update_interval == timedelta(minutes=5)


class TestWebSocketPollIntervalAdaptation:
    """Test that poll interval adapts based on WebSocket connection state."""

    async def test_ws_connect_extends_poll_interval(self, coordinator: GardenaCoordinator) -> None:
        coordinator._client = AsyncMock()
        coordinator._client.async_get_websocket_url = AsyncMock(
            return_value="wss://gardena.example/ws"
        )

        with patch(_PATCH_WS) as mock_ws_cls:
            mock_ws_cls.return_value = AsyncMock()
            await coordinator._async_start_websocket({})

        assert coordinator.update_interval == SCAN_INTERVAL_WS_CONNECTED

    def test_ws_error_restores_short_poll_interval(self, coordinator: GardenaCoordinator) -> None:
        coordinator._ws_connected = True
        coordinator.update_interval = SCAN_INTERVAL_WS_CONNECTED

        coordinator._on_ws_error(RuntimeError("connection lost"))

        assert coordinator.update_interval == SCAN_INTERVAL
        assert coordinator._ws_connected is False


class TestWebSocketAuthReauth:
    """Test that WebSocket auth errors trigger reauth."""

    def test_ws_auth_error_triggers_reauth(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        from aiogardenasmart.exceptions import GardenaAuthenticationError

        with patch.object(coordinator.config_entry, "async_start_reauth") as mock_reauth:
            coordinator._on_ws_error(GardenaAuthenticationError("token expired"))

        mock_reauth.assert_called_once_with(hass)

    def test_ws_auth_error_does_not_create_repair_issue(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        from aiogardenasmart.exceptions import GardenaAuthenticationError

        with patch.object(coordinator.config_entry, "async_start_reauth"):
            coordinator._on_ws_error(GardenaAuthenticationError("token expired"))

        issue_reg = ir.async_get(hass)
        assert issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed") is None

    def test_ws_non_auth_error_still_creates_repair_issue(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        for _ in range(WS_REPAIR_ISSUE_THRESHOLD):
            coordinator._on_ws_error(RuntimeError("network error"))
            coordinator._cancel_ws_reconnect()

        issue_reg = ir.async_get(hass)
        assert issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed") is not None


class TestWebSocketAutoReconnect:
    """Test automatic WebSocket reconnection with exponential backoff."""

    def test_ws_error_schedules_reconnect_task(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        coordinator._on_ws_error(RuntimeError("connection lost"))
        assert coordinator._ws_reconnect_task is not None
        assert not coordinator._ws_reconnect_task.done()
        coordinator._cancel_ws_reconnect()

    def test_ws_error_does_not_duplicate_reconnect_task(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        coordinator._on_ws_error(RuntimeError("lost"))
        first_task = coordinator._ws_reconnect_task
        coordinator._schedule_ws_reconnect()  # should not replace
        assert coordinator._ws_reconnect_task is first_task
        coordinator._cancel_ws_reconnect()

    def test_ws_auth_error_does_not_schedule_reconnect(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        from aiogardenasmart.exceptions import GardenaAuthenticationError

        with patch.object(coordinator.config_entry, "async_start_reauth"):
            coordinator._on_ws_error(GardenaAuthenticationError("expired"))
        assert coordinator._ws_reconnect_task is None

    async def test_reconnect_loop_succeeds(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        coordinator.data = {"dev-1": MagicMock()}

        with (
            patch.object(
                coordinator, "_async_start_websocket", new_callable=AsyncMock
            ) as mock_start,
            patch(
                "custom_components.gardena_smart_system.base_coordinator.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            # Simulate: first attempt fails, second succeeds
            call_count = 0

            async def _side_effect(devices):
                nonlocal call_count
                call_count += 1
                if call_count >= 2:
                    coordinator._ws_connected = True

            mock_start.side_effect = _side_effect
            await coordinator._async_ws_reconnect_loop()

        assert coordinator._ws_connected is True
        assert mock_start.call_count == 2

    async def test_reconnect_loop_gives_up_after_max_attempts(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        coordinator.data = {"dev-1": MagicMock()}

        with (
            patch.object(
                coordinator, "_async_start_websocket", new_callable=AsyncMock
            ) as mock_start,
            patch(
                "custom_components.gardena_smart_system.base_coordinator.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            await coordinator._async_ws_reconnect_loop()

        assert coordinator._ws_connected is False
        assert mock_start.call_count == len(coordinator._WS_RECONNECT_DELAYS)

    def test_cancel_ws_reconnect(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        coordinator._on_ws_error(RuntimeError("lost"))
        assert coordinator._ws_reconnect_task is not None
        coordinator._cancel_ws_reconnect()
        assert coordinator._ws_reconnect_task is None

    async def test_shutdown_cancels_reconnect_task(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        coordinator._on_ws_error(RuntimeError("lost"))
        assert coordinator._ws_reconnect_task is not None
        await coordinator.async_shutdown()
        assert coordinator._ws_reconnect_task is None

    async def test_successful_ws_start_cancels_reconnect(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        coordinator._on_ws_error(RuntimeError("lost"))
        assert coordinator._ws_reconnect_task is not None

        coordinator._client = AsyncMock()
        coordinator._client.async_get_websocket_url = AsyncMock(
            return_value="wss://gardena.example/ws"
        )
        with patch(_PATCH_WS) as mock_ws_cls:
            mock_ws_cls.return_value = AsyncMock()
            await coordinator._async_start_websocket({})

        assert coordinator._ws_connected is True
        assert coordinator._ws_reconnect_task is None


class TestWebSocketCircuitBreaker:
    """Test the WebSocket circuit breaker cooldown mechanism."""

    def test_failure_counter_increments_on_ws_error(self, coordinator: GardenaCoordinator) -> None:
        assert coordinator._ws_consecutive_failures == 0
        coordinator._on_ws_error(RuntimeError("lost"))
        assert coordinator._ws_consecutive_failures == 1
        coordinator._cancel_ws_reconnect()
        coordinator._on_ws_error(RuntimeError("lost again"))
        assert coordinator._ws_consecutive_failures == 2
        coordinator._cancel_ws_reconnect()

    def test_cooldown_activates_after_threshold(self, coordinator: GardenaCoordinator) -> None:
        # Two failures below threshold → no cooldown
        coordinator._record_ws_failure()
        coordinator._record_ws_failure()
        assert coordinator._ws_cooldown_until == 0.0

        # Third failure triggers 15 min cooldown
        before = time.monotonic()
        coordinator._record_ws_failure()
        assert coordinator._ws_cooldown_until >= before + 15 * 60 - 1

    def test_cooldown_escalates_with_more_failures(self, coordinator: GardenaCoordinator) -> None:
        for _ in range(5):
            coordinator._record_ws_failure()
        cooldown_5 = coordinator._ws_cooldown_until - time.monotonic()
        assert cooldown_5 >= 30 * 60 - 1  # 30 min after 5 failures

        for _ in range(2):
            coordinator._record_ws_failure()
        cooldown_7 = coordinator._ws_cooldown_until - time.monotonic()
        assert cooldown_7 >= 60 * 60 - 1  # 60 min after 7 failures

    async def test_start_websocket_respects_cooldown(self, coordinator: GardenaCoordinator) -> None:
        coordinator._ws_cooldown_until = time.monotonic() + 900
        coordinator._client = AsyncMock()
        coordinator._client.async_get_websocket_url = AsyncMock(
            return_value="wss://gardena.example/ws"
        )

        with patch(_PATCH_WS) as mock_ws_cls:
            await coordinator._async_start_websocket({})

        # No WebSocket construction attempted
        mock_ws_cls.assert_not_called()
        coordinator._client.async_get_websocket_url.assert_not_called()
        assert coordinator._ws_connected is False

    async def test_reconnect_loop_aborts_when_cooldown_active(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        coordinator.data = {"dev-1": MagicMock()}

        with (
            patch.object(
                coordinator, "_async_start_websocket", new_callable=AsyncMock
            ) as mock_start,
            patch(
                "custom_components.gardena_smart_system.base_coordinator.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            # First attempt: bump into cooldown mid-loop
            async def _side_effect(devices):
                coordinator._ws_cooldown_until = time.monotonic() + 900

            mock_start.side_effect = _side_effect
            await coordinator._async_ws_reconnect_loop()

        # Should have aborted after the first attempt set cooldown
        assert mock_start.call_count == 1

    async def test_successful_connect_resets_failure_counter(
        self, coordinator: GardenaCoordinator
    ) -> None:
        coordinator._ws_consecutive_failures = 4
        coordinator._ws_cooldown_until = time.monotonic() + 900

        # Let cooldown expire so the connect proceeds
        coordinator._ws_cooldown_until = 0.0

        coordinator._client = AsyncMock()
        coordinator._client.async_get_websocket_url = AsyncMock(
            return_value="wss://gardena.example/ws"
        )
        with patch(_PATCH_WS) as mock_ws_cls:
            mock_ws_cls.return_value = AsyncMock()
            await coordinator._async_start_websocket({})

        assert coordinator._ws_connected is True
        assert coordinator._ws_consecutive_failures == 0
        assert coordinator._ws_cooldown_until == 0.0


class TestRepairFlow:
    """Test the WebSocketReconnectRepairFlow."""

    async def test_repair_flow_creation(self, hass: HomeAssistant) -> None:
        """Test that async_create_fix_flow returns a WebSocketReconnectRepairFlow."""
        from custom_components.gardena_smart_system.repairs import (
            WebSocketReconnectRepairFlow,
            async_create_fix_flow,
        )

        flow = await async_create_fix_flow(hass, "websocket_connection_failed", None)
        assert isinstance(flow, WebSocketReconnectRepairFlow)

    async def test_repair_flow_triggers_refresh_on_confirm(
        self, hass: HomeAssistant, entry: MockConfigEntry, coordinator: GardenaCoordinator
    ) -> None:
        """Test that confirming the repair flow refreshes coordinators."""
        from custom_components.gardena_smart_system.repairs import (
            WebSocketReconnectRepairFlow,
        )

        # Attach coordinator as runtime_data on the entry
        entry.runtime_data = coordinator

        flow = WebSocketReconnectRepairFlow()
        flow.hass = hass

        with patch.object(
            coordinator, "async_request_refresh", new_callable=AsyncMock
        ) as mock_refresh:
            result = await flow.async_step_init(user_input={})

        mock_refresh.assert_called_once()
        assert result["type"] == "create_entry"


class TestCommandThrottle:
    """Test command throttling (token-bucket model)."""

    def test_first_command_allowed(self, coordinator: GardenaCoordinator) -> None:
        # Should not raise
        coordinator.check_command_throttle()

    def test_burst_of_ten_rapid_commands_allowed(self, coordinator: GardenaCoordinator) -> None:
        """The bucket holds up to COMMAND_BURST_CAPACITY (10) tokens."""
        from custom_components.gardena_smart_system.const import COMMAND_BURST_CAPACITY

        for _ in range(COMMAND_BURST_CAPACITY):
            coordinator.check_command_throttle()

    def test_eleventh_rapid_command_blocked(self, coordinator: GardenaCoordinator) -> None:
        """After the burst is exhausted, the next command is rejected."""
        from custom_components.gardena_smart_system.const import COMMAND_BURST_CAPACITY

        for _ in range(COMMAND_BURST_CAPACITY):
            coordinator.check_command_throttle()

        with pytest.raises(HomeAssistantError):
            coordinator.check_command_throttle()

    def test_command_allowed_after_refill_interval(self, coordinator: GardenaCoordinator) -> None:
        """After MIN_COMMAND_INTERVAL_SECONDS, one token is back."""
        from custom_components.gardena_smart_system.const import (
            COMMAND_BURST_CAPACITY,
            MIN_COMMAND_INTERVAL_SECONDS,
        )

        for _ in range(COMMAND_BURST_CAPACITY):
            coordinator.check_command_throttle()

        # Simulate one refill interval passing
        coordinator._command_tokens_updated = time.monotonic() - MIN_COMMAND_INTERVAL_SECONDS - 0.1

        # Should not raise — one token has refilled
        coordinator.check_command_throttle()

    def test_tokens_capped_at_capacity(self, coordinator: GardenaCoordinator) -> None:
        """Long idle periods do not grow the bucket beyond its capacity."""
        from custom_components.gardena_smart_system.const import COMMAND_BURST_CAPACITY

        # Simulate one hour of idleness — refill formula would yield ~720
        # tokens, but the bucket is capped at COMMAND_BURST_CAPACITY.
        coordinator._command_tokens_updated = time.monotonic() - 3600

        for _ in range(COMMAND_BURST_CAPACITY):
            coordinator.check_command_throttle()

        # The (capacity + 1)th command must still be blocked.
        with pytest.raises(HomeAssistantError):
            coordinator.check_command_throttle()


class TestWebSocketWatchdog:
    """Test the WebSocket watchdog that detects stale connections."""

    async def test_watchdog_ignores_healthy_connection(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        """Watchdog does nothing when WS recently received messages."""
        ws = MagicMock()
        coordinator._ws = ws
        coordinator._ws_connected = True

        # now=1000, last_message_time=999 → silence=1s < WS_WATCHDOG_TIMEOUT_SECONDS(300)
        _BASE = "custom_components.gardena_smart_system.base_coordinator.time"
        with patch(_BASE + ".monotonic", return_value=1000.0):
            ws.last_message_time = 999.0
            await coordinator._async_ws_watchdog_check()

        # Should still be connected
        assert coordinator._ws_connected is True
        ws.async_disconnect.assert_not_called()

    async def test_watchdog_disconnects_stale_connection(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        """Watchdog forces disconnect when no message received for too long."""
        ws = AsyncMock()
        coordinator._ws = ws
        coordinator._ws_connected = True

        # Patch time.monotonic in the module under test so the test is not
        # affected by freezegun or other time mocking in the HA test harness.
        # now=1000, last_message_time=400 → silence=600s > WS_WATCHDOG_TIMEOUT_SECONDS(300)
        _BASE = "custom_components.gardena_smart_system.base_coordinator.time"
        with (
            patch(_BASE + ".monotonic", return_value=1000.0),
            patch.object(coordinator, "async_request_refresh", new_callable=AsyncMock),
        ):
            ws.last_message_time = 400.0
            await coordinator._async_ws_watchdog_check()

        assert coordinator._ws_connected is False
        assert coordinator._ws is None
        ws.async_disconnect.assert_called_once()

    async def test_watchdog_skips_when_not_connected(self, coordinator: GardenaCoordinator) -> None:
        """Watchdog is a no-op when WS is not connected."""
        coordinator._ws = None
        coordinator._ws_connected = False

        # Should not raise
        await coordinator._async_ws_watchdog_check()

    async def test_watchdog_schedules_reconnect_without_extra_poll(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        """Watchdog triggers WS reconnect but does NOT force an extra REST poll.

        The previous implementation called async_request_refresh() which
        doubled the API-call cost per watchdog event. The reconnect loop alone
        is enough — REST state catches up on the next scheduled coordinator
        tick (update_interval is lowered to scan_interval by the watchdog).
        """
        ws = AsyncMock()
        coordinator._ws = ws
        coordinator._ws_connected = True

        _BASE = "custom_components.gardena_smart_system.base_coordinator.time"
        with (
            patch(_BASE + ".monotonic", return_value=1000.0),
            patch.object(
                coordinator, "async_request_refresh", new_callable=AsyncMock
            ) as mock_refresh,
            patch.object(coordinator, "_schedule_ws_reconnect") as mock_schedule,
        ):
            ws.last_message_time = 400.0
            await coordinator._async_ws_watchdog_check()

        mock_refresh.assert_not_called()
        mock_schedule.assert_called_once()


class TestApiBudgetTracker:
    """Test the ApiBudgetTracker class."""

    async def test_initial_state_zero(self, hass: HomeAssistant) -> None:
        from homeassistant.helpers.storage import Store

        from custom_components.gardena_smart_system.base_coordinator import ApiBudgetTracker

        store = Store(hass, 1, "test_budget")
        tracker = ApiBudgetTracker(store)

        await tracker.async_load()

        assert tracker.request_count == 0
        assert tracker.remaining_percent == 100.0

    async def test_increment_increases_count(self, hass: HomeAssistant) -> None:
        from homeassistant.helpers.storage import Store

        from custom_components.gardena_smart_system.base_coordinator import ApiBudgetTracker

        store = Store(hass, 1, "test_budget_inc")
        tracker = ApiBudgetTracker(store)
        await tracker.async_load()

        tracker.increment()
        assert tracker.request_count == 1

        tracker.increment(5)
        assert tracker.request_count == 6

    async def test_remaining_percent_decreases(self, hass: HomeAssistant) -> None:
        from homeassistant.helpers.storage import Store

        from custom_components.gardena_smart_system.base_coordinator import ApiBudgetTracker

        store = Store(hass, 1, "test_budget_pct")
        tracker = ApiBudgetTracker(store, budget=100)
        await tracker.async_load()

        tracker.increment(25)
        assert tracker.remaining_percent == 75.0

        tracker.increment(75)
        assert tracker.remaining_percent == 0.0

    async def test_remaining_percent_floor_at_zero(self, hass: HomeAssistant) -> None:
        from homeassistant.helpers.storage import Store

        from custom_components.gardena_smart_system.base_coordinator import ApiBudgetTracker

        store = Store(hass, 1, "test_budget_floor")
        tracker = ApiBudgetTracker(store, budget=10)
        await tracker.async_load()

        tracker.increment(20)
        assert tracker.remaining_percent == 0.0

    async def test_month_property(self, hass: HomeAssistant) -> None:
        from homeassistant.helpers.storage import Store
        from homeassistant.util import dt as dt_util

        from custom_components.gardena_smart_system.base_coordinator import ApiBudgetTracker

        store = Store(hass, 1, "test_budget_month")
        tracker = ApiBudgetTracker(store)
        await tracker.async_load()

        expected_month = dt_util.now().strftime("%Y-%m")
        assert tracker.month == expected_month

    async def test_month_rollover_resets_count(self, hass: HomeAssistant) -> None:
        from unittest.mock import patch as _patch

        from homeassistant.helpers.storage import Store

        from custom_components.gardena_smart_system.base_coordinator import ApiBudgetTracker

        store = Store(hass, 1, "test_budget_rollover")
        tracker = ApiBudgetTracker(store)
        await tracker.async_load()

        tracker.increment(50)
        assert tracker.request_count == 50

        with _patch("custom_components.gardena_smart_system.base_coordinator.dt_util") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2099-01"
            tracker.increment(1)

        assert tracker.request_count == 1

    async def test_persistence_across_load(self, hass: HomeAssistant) -> None:
        from homeassistant.helpers.storage import Store
        from homeassistant.util import dt as dt_util

        from custom_components.gardena_smart_system.base_coordinator import ApiBudgetTracker

        store = Store(hass, 1, "test_budget_persist")
        tracker = ApiBudgetTracker(store)
        await tracker.async_load()

        tracker.increment(42)

        current_month = dt_util.now().strftime("%Y-%m")
        await store.async_save({"month": current_month, "request_count": 42})

        tracker2 = ApiBudgetTracker(store)
        await tracker2.async_load()

        assert tracker2.request_count == 42
        assert tracker2.month == current_month

    async def test_stale_month_data_resets_on_load(self, hass: HomeAssistant) -> None:
        from homeassistant.helpers.storage import Store

        from custom_components.gardena_smart_system.base_coordinator import ApiBudgetTracker

        store = Store(hass, 1, "test_budget_stale")
        await store.async_save({"month": "2020-01", "request_count": 9999})

        tracker = ApiBudgetTracker(store)
        await tracker.async_load()

        assert tracker.request_count == 0

    def test_budget_property(self, hass: HomeAssistant) -> None:
        from homeassistant.helpers.storage import Store

        from custom_components.gardena_smart_system.base_coordinator import ApiBudgetTracker

        store = Store(hass, 1, "test_budget_prop")
        tracker = ApiBudgetTracker(store, budget=5000)

        assert tracker.budget == 5000

    async def test_coordinator_exposes_api_budget(self, coordinator: GardenaCoordinator) -> None:
        from custom_components.gardena_smart_system.base_coordinator import ApiBudgetTracker

        assert isinstance(coordinator.api_budget, ApiBudgetTracker)

    async def test_async_reset_clears_counter_and_persists(self, hass: HomeAssistant) -> None:
        """Reset zeros the counter and writes to the Store immediately."""
        from homeassistant.helpers.storage import Store

        from custom_components.gardena_smart_system.base_coordinator import (
            ApiBudgetTracker,
        )

        store: Store = Store(hass, 1, "test_budget_reset")
        tracker = ApiBudgetTracker(store)
        await tracker.async_load()
        tracker.increment(1234)
        assert tracker.request_count == 1234

        await tracker.async_reset()

        assert tracker.request_count == 0
        # Re-hydrate from disk to prove the reset was persisted
        tracker2 = ApiBudgetTracker(store)
        await tracker2.async_load()
        assert tracker2.request_count == 0

    async def test_module_reset_helper_overwrites_entry_store(self, hass: HomeAssistant) -> None:
        """`async_reset_api_budget_store` wipes the file used by an entry's tracker."""
        from homeassistant.helpers.storage import Store

        from custom_components.gardena_smart_system.base_coordinator import (
            ApiBudgetTracker,
            async_reset_api_budget_store,
        )
        from custom_components.gardena_smart_system.const import (
            DOMAIN,
            STORAGE_VERSION_API_BUDGET,
        )

        entry_id = "abc123"
        store_key = f"{DOMAIN}.{entry_id}.api_budget"
        store: Store = Store(hass, STORAGE_VERSION_API_BUDGET, store_key)

        # Seed: an existing tracker with some usage
        tracker = ApiBudgetTracker(store)
        await tracker.async_load()
        tracker.increment(999)
        # Force the delayed save so it hits disk before we reset
        await store.async_save({"month": tracker.month, "request_count": 999})

        await async_reset_api_budget_store(hass, entry_id)

        # A freshly loaded tracker must see 0, confirming the reset persisted
        fresh_tracker = ApiBudgetTracker(store)
        await fresh_tracker.async_load()
        assert fresh_tracker.request_count == 0

    async def test_poll_increments_budget(self, coordinator: GardenaCoordinator) -> None:
        devices = {"dev-1": make_mock_device()}
        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(return_value=devices)
        await coordinator.api_budget.async_load()

        initial = coordinator.api_budget.request_count

        with patch.object(coordinator, "_async_start_websocket", new_callable=AsyncMock):
            await coordinator._async_update_data()

        assert coordinator.api_budget.request_count == initial + 1


class TestApiBudgetAutoStop:
    """Test the auto-stop safety net that pauses API activity near budget exhaustion."""

    async def test_is_exhausted_false_with_headroom(self, hass: HomeAssistant) -> None:
        from homeassistant.helpers.storage import Store

        from custom_components.gardena_smart_system.base_coordinator import ApiBudgetTracker

        store = Store(hass, 1, "test_autostop_headroom")
        tracker = ApiBudgetTracker(store, budget=100)
        await tracker.async_load()

        tracker.increment(50)

        assert tracker.is_exhausted is False

    async def test_is_exhausted_true_near_limit(self, hass: HomeAssistant) -> None:
        from homeassistant.helpers.storage import Store

        from custom_components.gardena_smart_system.base_coordinator import ApiBudgetTracker

        store = Store(hass, 1, "test_autostop_near")
        tracker = ApiBudgetTracker(store, budget=100)
        await tracker.async_load()

        # 96 / 100 consumed → 4% remaining → below 5% threshold
        tracker.increment(96)

        assert tracker.is_exhausted is True

    async def test_is_exhausted_resets_on_month_rollover(self, hass: HomeAssistant) -> None:
        from unittest.mock import patch as _patch

        from homeassistant.helpers.storage import Store

        from custom_components.gardena_smart_system.base_coordinator import ApiBudgetTracker

        store = Store(hass, 1, "test_autostop_rollover")
        tracker = ApiBudgetTracker(store, budget=100)
        await tracker.async_load()

        tracker.increment(99)
        assert tracker.is_exhausted is True

        with _patch("custom_components.gardena_smart_system.base_coordinator.dt_util") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2099-01"
            assert tracker.is_exhausted is False

    async def test_update_raises_when_exhausted(self, coordinator: GardenaCoordinator) -> None:
        await coordinator.api_budget.async_load()
        coordinator.api_budget.increment(coordinator.api_budget.budget)
        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock()

        with pytest.raises(UpdateFailed, match="budget nearly exhausted"):
            await coordinator._async_update_data()

        coordinator._client.async_get_devices.assert_not_called()

    async def test_command_throttle_raises_when_exhausted(
        self, coordinator: GardenaCoordinator
    ) -> None:
        await coordinator.api_budget.async_load()
        coordinator.api_budget.increment(coordinator.api_budget.budget)

        with pytest.raises(HomeAssistantError) as excinfo:
            coordinator.check_command_throttle()

        assert excinfo.value.translation_key == "api_budget_exhausted"

    async def test_command_throttle_works_below_threshold(
        self, coordinator: GardenaCoordinator
    ) -> None:
        await coordinator.api_budget.async_load()
        # 50% of budget still available → well above 5% threshold
        coordinator.api_budget.increment(coordinator.api_budget.budget // 2)

        coordinator.check_command_throttle()  # must not raise

    async def test_poll_increments_budget_even_on_connection_error(
        self, coordinator: GardenaCoordinator
    ) -> None:
        """Failed polls still consume server-side quota → must count locally."""
        from aiogardenasmart.exceptions import GardenaConnectionError

        await coordinator.api_budget.async_load()
        initial = coordinator.api_budget.request_count

        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(
            side_effect=GardenaConnectionError("unreachable")
        )

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        assert coordinator.api_budget.request_count == initial + 1

    async def test_poll_increments_budget_on_rate_limit(
        self, coordinator: GardenaCoordinator
    ) -> None:
        """Rate-limit responses were billed server-side → must count locally."""
        from aiogardenasmart.exceptions import GardenaRateLimitError

        await coordinator.api_budget.async_load()
        initial = coordinator.api_budget.request_count

        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(side_effect=GardenaRateLimitError("429"))

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        assert coordinator.api_budget.request_count == initial + 1

    async def test_start_websocket_aborts_when_exhausted(
        self, coordinator: GardenaCoordinator
    ) -> None:
        """WS connect must not call the API when the budget is exhausted."""
        await coordinator.api_budget.async_load()
        coordinator.api_budget.increment(coordinator.api_budget.budget)

        coordinator._client = AsyncMock()
        coordinator._client.async_get_websocket_url = AsyncMock(return_value="wss://x")

        await coordinator._async_start_websocket({})

        coordinator._client.async_get_websocket_url.assert_not_called()
        assert coordinator._ws_connected is False
