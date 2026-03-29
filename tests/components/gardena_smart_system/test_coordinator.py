"""Tests for the Gardena Smart System DataUpdateCoordinator."""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

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
        # Create the repair issue first
        coordinator._on_ws_error(RuntimeError("lost"))

        issue_reg = ir.async_get(hass)
        assert issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed") is not None

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
    def test_ws_error_creates_repair_issue(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        coordinator._on_ws_error(RuntimeError("connection dropped"))

        issue_reg = ir.async_get(hass)
        issue = issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed")
        assert issue is not None
        assert issue.severity == ir.IssueSeverity.WARNING
        assert issue.is_fixable

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
        """After a successful fetch, the next rate limit starts at 5 min again."""
        from aiogardenasmart.exceptions import GardenaRateLimitError

        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(side_effect=GardenaRateLimitError("429"))

        # Two rate-limit hits (5min, 10min)
        for _ in range(2):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()
        assert coordinator.update_interval == timedelta(minutes=10)

        # Successful fetch resets counter
        devices = {"dev-1": MagicMock()}
        coordinator._client.async_get_devices = AsyncMock(return_value=devices)
        with patch.object(coordinator, "_async_start_websocket", new_callable=AsyncMock):
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
        coordinator._on_ws_error(RuntimeError("network error"))

        issue_reg = ir.async_get(hass)
        assert issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed") is not None


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
    """Test command throttling to prevent API quota exhaustion."""

    def test_first_command_allowed(self, coordinator: GardenaCoordinator) -> None:
        # Should not raise
        coordinator.check_command_throttle()

    def test_rapid_second_command_blocked(self, coordinator: GardenaCoordinator) -> None:
        coordinator.check_command_throttle()  # first succeeds

        with pytest.raises(HomeAssistantError):
            coordinator.check_command_throttle()  # immediate second blocked

    def test_command_allowed_after_interval(self, coordinator: GardenaCoordinator) -> None:
        coordinator.check_command_throttle()

        # Simulate time passing
        coordinator._last_command_time = time.monotonic() - 10

        # Should not raise
        coordinator.check_command_throttle()
