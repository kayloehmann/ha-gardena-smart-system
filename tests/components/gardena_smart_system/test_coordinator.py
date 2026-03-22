"""Tests for the Gardena Smart System DataUpdateCoordinator."""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import MockConfigEntry  # type: ignore[no-redef]

from custom_components.gardena_smart_system.const import (
    DOMAIN,
    RATE_LIMIT_COOLDOWN,
    SCAN_INTERVAL,
    SCAN_INTERVAL_WS_CONNECTED,
)
from custom_components.gardena_smart_system.coordinator import GardenaCoordinator

from .conftest import ENTRY_DATA, make_mock_device

_PATCH_WS = (
    "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"
)


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
    async def test_returns_devices_from_api(
        self, coordinator: GardenaCoordinator
    ) -> None:
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
    async def test_websocket_connected_on_success(
        self, coordinator: GardenaCoordinator
    ) -> None:
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

    async def test_websocket_reconnect_clears_repair_issue(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        # Create the repair issue first
        coordinator._on_ws_error(RuntimeError("lost"))

        issue_reg = ir.async_get(hass)
        assert issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed") is not None

        # Reconnect should clear it
        coordinator._client = AsyncMock()
        coordinator._client.async_get_websocket_url = AsyncMock(
            return_value="wss://test"
        )
        with patch(_PATCH_WS) as mock_ws_cls:
            mock_ws_cls.return_value = AsyncMock()
            await coordinator._async_start_websocket({})

        assert issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed") is None


class TestOnDeviceUpdate:
    def test_device_update_replaces_device_in_data(
        self, coordinator: GardenaCoordinator
    ) -> None:
        old_device = make_mock_device("dev-1", "SN001")
        coordinator.data = {"dev-1": old_device}

        new_device = make_mock_device("dev-1", "SN001", name="Updated")
        coordinator._on_device_update("dev-1", new_device)

        assert coordinator.data["dev-1"] is new_device

    def test_device_update_with_no_existing_data(
        self, coordinator: GardenaCoordinator
    ) -> None:
        coordinator.data = None
        device = make_mock_device()
        # Should not raise
        coordinator._on_device_update("dev-1", device)


class TestStaleDevices:
    async def test_stale_device_removed_from_ha_registry(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        old_device = make_mock_device("old-dev", "SN-OLD")
        new_device = make_mock_device("new-dev", "SN-NEW")
        coordinator.data = {"old-dev": old_device}

        # Register the old device in HA device registry
        dev_reg = dr.async_get(hass)
        dev_reg.async_get_or_create(
            config_entry_id=coordinator.config_entry.entry_id,
            identifiers={(DOMAIN, "SN-OLD")},
        )
        assert dev_reg.async_get_device(identifiers={(DOMAIN, "SN-OLD")}) is not None

        # New poll only returns the new device
        coordinator._async_remove_stale_devices({"new-dev": new_device})

        assert dev_reg.async_get_device(identifiers={(DOMAIN, "SN-OLD")}) is None

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

        # Same device still in fresh data — should not be removed
        coordinator._async_remove_stale_devices({device.device_id: device})

        assert dev_reg.async_get_device(identifiers={(DOMAIN, device.serial)}) is not None

    def test_no_op_on_first_poll_when_data_is_none(
        self, coordinator: GardenaCoordinator
    ) -> None:
        coordinator.data = None
        # Should not raise
        coordinator._async_remove_stale_devices({})

    def test_device_without_serial_skipped(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        device = make_mock_device()
        device.serial = None  # No serial — skip registry removal
        coordinator.data = {device.device_id: device}

        # Should not raise or try registry lookup
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
        assert not issue.is_fixable

    def test_ws_error_sets_connected_false(
        self, coordinator: GardenaCoordinator
    ) -> None:
        coordinator._ws_connected = True
        coordinator._on_ws_error(RuntimeError("dropped"))
        assert coordinator._ws_connected is False


class TestShutdown:
    async def test_shutdown_disconnects_websocket(
        self, coordinator: GardenaCoordinator
    ) -> None:
        mock_ws = AsyncMock()
        mock_ws.async_disconnect = AsyncMock()
        coordinator._ws = mock_ws
        coordinator._ws_connected = True

        await coordinator.async_shutdown()

        mock_ws.async_disconnect.assert_called_once()
        assert coordinator._ws is None
        assert coordinator._ws_connected is False

    async def test_shutdown_with_no_websocket(
        self, coordinator: GardenaCoordinator
    ) -> None:
        coordinator._ws = None
        # Should not raise
        await coordinator.async_shutdown()


class TestRateLimitBackoff:
    """Test rate limit handling in _async_update_data."""

    async def test_rate_limit_raises_update_failed(
        self, coordinator: GardenaCoordinator
    ) -> None:
        from aiogardenasmart.exceptions import GardenaRateLimitError

        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(
            side_effect=GardenaRateLimitError("429")
        )

        with pytest.raises(UpdateFailed, match="Rate limited"):
            await coordinator._async_update_data()

    async def test_rate_limit_increases_poll_interval(
        self, coordinator: GardenaCoordinator
    ) -> None:
        from aiogardenasmart.exceptions import GardenaRateLimitError

        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(
            side_effect=GardenaRateLimitError("429")
        )

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        assert coordinator.update_interval == RATE_LIMIT_COOLDOWN

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

    async def test_consecutive_rate_limits_keep_cooldown(
        self, coordinator: GardenaCoordinator
    ) -> None:
        from aiogardenasmart.exceptions import GardenaRateLimitError

        coordinator._client = AsyncMock()
        coordinator._client.async_get_devices = AsyncMock(
            side_effect=GardenaRateLimitError("429")
        )

        for _ in range(3):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()
            assert coordinator.update_interval == RATE_LIMIT_COOLDOWN


class TestWebSocketPollIntervalAdaptation:
    """Test that poll interval adapts based on WebSocket connection state."""

    async def test_ws_connect_extends_poll_interval(
        self, coordinator: GardenaCoordinator
    ) -> None:
        coordinator._client = AsyncMock()
        coordinator._client.async_get_websocket_url = AsyncMock(
            return_value="wss://gardena.example/ws"
        )

        with patch(_PATCH_WS) as mock_ws_cls:
            mock_ws_cls.return_value = AsyncMock()
            await coordinator._async_start_websocket({})

        assert coordinator.update_interval == SCAN_INTERVAL_WS_CONNECTED

    def test_ws_error_restores_short_poll_interval(
        self, coordinator: GardenaCoordinator
    ) -> None:
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

        with patch.object(
            coordinator.config_entry, "async_start_reauth"
        ) as mock_reauth:
            coordinator._on_ws_error(
                GardenaAuthenticationError("token expired")
            )

        mock_reauth.assert_called_once_with(hass)

    def test_ws_auth_error_does_not_create_repair_issue(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        from aiogardenasmart.exceptions import GardenaAuthenticationError

        with patch.object(coordinator.config_entry, "async_start_reauth"):
            coordinator._on_ws_error(
                GardenaAuthenticationError("token expired")
            )

        issue_reg = ir.async_get(hass)
        assert issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed") is None

    def test_ws_non_auth_error_still_creates_repair_issue(
        self, hass: HomeAssistant, coordinator: GardenaCoordinator
    ) -> None:
        coordinator._on_ws_error(RuntimeError("network error"))

        issue_reg = ir.async_get(hass)
        assert issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed") is not None


class TestCommandThrottle:
    """Test command throttling to prevent API quota exhaustion."""

    def test_first_command_allowed(
        self, coordinator: GardenaCoordinator
    ) -> None:
        # Should not raise
        coordinator.check_command_throttle()

    def test_rapid_second_command_blocked(
        self, coordinator: GardenaCoordinator
    ) -> None:
        coordinator.check_command_throttle()  # first succeeds

        with pytest.raises(HomeAssistantError):
            coordinator.check_command_throttle()  # immediate second blocked

    def test_command_allowed_after_interval(
        self, coordinator: GardenaCoordinator
    ) -> None:
        coordinator.check_command_throttle()

        # Simulate time passing
        coordinator._last_command_time = time.monotonic() - 10

        # Should not raise
        coordinator.check_command_throttle()
