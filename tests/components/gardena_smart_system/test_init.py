"""Tests for Gardena Smart System integration setup and teardown."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,  # type: ignore[no-redef]
    )

from custom_components.gardena_smart_system.const import (
    API_TYPE_GARDENA,
    CONF_API_TYPE,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_LOCATION_ID,
    DOMAIN,
)

from .conftest import ENTRY_DATA, MOCK_CLIENT_ID, MOCK_CLIENT_SECRET, MOCK_LOCATION_ID

_PATCH_CLIENT = "custom_components.gardena_smart_system.coordinator.GardenaClient"
_PATCH_AUTH = "custom_components.gardena_smart_system.coordinator.GardenaAuth"
_PATCH_WS = "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"


@pytest.fixture
def mock_api(mock_devices: dict) -> object:
    """Patch all aiogardenasmart classes used by the coordinator."""
    with (
        patch(_PATCH_CLIENT) as mock_client_cls,
        patch(_PATCH_AUTH, return_value=AsyncMock()),
        patch(_PATCH_WS) as mock_ws_cls,
    ):
        mock_client = AsyncMock()
        mock_client.async_get_devices = AsyncMock(return_value=mock_devices)
        mock_client.async_get_websocket_url = AsyncMock(return_value="wss://test")
        mock_client_cls.return_value = mock_client

        mock_ws = AsyncMock()
        mock_ws.async_connect = AsyncMock()
        mock_ws.async_disconnect = AsyncMock()
        mock_ws_cls.return_value = mock_ws

        yield mock_client


class TestSetupEntry:
    async def test_setup_entry_loads_successfully(
        self,
        hass: HomeAssistant,
        mock_config_entry: object,
        mock_api: object,
    ) -> None:
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert mock_config_entry.state is ConfigEntryState.LOADED

    async def test_setup_entry_creates_coordinator_runtime_data(
        self,
        hass: HomeAssistant,
        mock_config_entry: object,
        mock_api: object,
    ) -> None:
        from custom_components.gardena_smart_system.coordinator import (
            GardenaCoordinator,
        )

        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert isinstance(mock_config_entry.runtime_data, GardenaCoordinator)

    async def test_setup_entry_auth_failure_sets_error_state(
        self,
        hass: HomeAssistant,
        mock_config_entry: object,
    ) -> None:
        from aiogardenasmart.exceptions import GardenaAuthenticationError

        with patch(_PATCH_CLIENT) as mock_cls, patch(_PATCH_AUTH, return_value=AsyncMock()):
            mock_client = AsyncMock()
            mock_client.async_get_devices = AsyncMock(
                side_effect=GardenaAuthenticationError("expired token")
            )
            mock_cls.return_value = mock_client

            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR

    async def test_setup_entry_connection_failure_sets_retry_state(
        self,
        hass: HomeAssistant,
        mock_config_entry: object,
    ) -> None:
        from aiogardenasmart.exceptions import GardenaConnectionError

        with patch(_PATCH_CLIENT) as mock_cls, patch(_PATCH_AUTH, return_value=AsyncMock()):
            mock_client = AsyncMock()
            mock_client.async_get_devices = AsyncMock(
                side_effect=GardenaConnectionError("connection refused")
            )
            mock_cls.return_value = mock_client

            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


class TestUnloadEntry:
    async def test_unload_entry_succeeds(
        self,
        hass: HomeAssistant,
        mock_config_entry: object,
        mock_api: object,
    ) -> None:
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert result is True
        assert mock_config_entry.state is ConfigEntryState.NOT_LOADED

    async def test_unload_calls_coordinator_shutdown(
        self,
        hass: HomeAssistant,
        mock_config_entry: object,
        mock_api: object,
    ) -> None:
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coordinator = mock_config_entry.runtime_data
        with patch.object(coordinator, "async_shutdown", new_callable=AsyncMock) as mock_shutdown:
            await hass.config_entries.async_unload(mock_config_entry.entry_id)
            await hass.async_block_till_done()

        mock_shutdown.assert_called_once()


class TestAsyncOptionsUpdated:
    """Test that options changes trigger a reload."""

    async def test_options_change_reloads_entry(
        self,
        hass: HomeAssistant,
        mock_config_entry: object,
        mock_api: object,
    ) -> None:
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert mock_config_entry.state is ConfigEntryState.LOADED

        # Update options — this triggers _async_options_updated → reload
        hass.config_entries.async_update_entry(
            mock_config_entry, options={"poll_interval_minutes": 60}
        )
        await hass.async_block_till_done()

        # After reload, the entry should still be loaded
        assert mock_config_entry.state is ConfigEntryState.LOADED


class TestAsyncRemoveConfigEntryDevice:
    """Test manual device removal from the device registry."""

    async def test_allows_removal_when_device_not_in_coordinator(
        self,
        hass: HomeAssistant,
        mock_config_entry: object,
        mock_api: object,
    ) -> None:
        """Devices not in coordinator data can be removed."""
        from custom_components.gardena_smart_system import (
            async_remove_config_entry_device,
        )

        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Create a device entry for a device NOT in coordinator data
        device_reg = dr.async_get(hass)
        device_entry = device_reg.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            identifiers={(DOMAIN, "OLD-SERIAL-NOT-IN-DATA")},
        )

        result = await async_remove_config_entry_device(hass, mock_config_entry, device_entry)
        assert result is True

    async def test_blocks_removal_when_device_still_in_coordinator(
        self,
        hass: HomeAssistant,
        mock_config_entry: object,
        mock_api: object,
    ) -> None:
        """Devices still present in coordinator data cannot be removed."""
        from custom_components.gardena_smart_system import (
            async_remove_config_entry_device,
        )

        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # The mock device has serial "SN001" — find the matching device entry
        device_reg = dr.async_get(hass)
        device_entry = device_reg.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            identifiers={(DOMAIN, "SN001")},
        )

        result = await async_remove_config_entry_device(hass, mock_config_entry, device_entry)
        assert result is False

    async def test_allows_removal_when_coordinator_data_is_empty(
        self,
        hass: HomeAssistant,
        mock_config_entry: object,
        mock_api: object,
    ) -> None:
        """When coordinator data is empty, all devices can be removed."""
        from custom_components.gardena_smart_system import (
            async_remove_config_entry_device,
        )

        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Clear coordinator data
        coordinator = mock_config_entry.runtime_data
        coordinator.async_set_updated_data({})

        device_reg = dr.async_get(hass)
        device_entry = device_reg.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            identifiers={(DOMAIN, "SN001")},
        )

        result = await async_remove_config_entry_device(hass, mock_config_entry, device_entry)
        assert result is True

    async def test_ignores_non_domain_identifiers(
        self,
        hass: HomeAssistant,
        mock_config_entry: object,
        mock_api: object,
    ) -> None:
        """Identifiers from other domains are skipped."""
        from custom_components.gardena_smart_system import (
            async_remove_config_entry_device,
        )

        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        device_reg = dr.async_get(hass)
        device_entry = device_reg.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            identifiers={("other_domain", "SN001")},
        )

        result = await async_remove_config_entry_device(hass, mock_config_entry, device_entry)
        assert result is True

    async def test_blocks_removal_with_serial_number_attr(
        self,
        hass: HomeAssistant,
        mock_config_entry: object,
        mock_api: object,
    ) -> None:
        """Also detects devices that use serial_number instead of serial."""
        from custom_components.gardena_smart_system import (
            async_remove_config_entry_device,
        )

        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Replace coordinator data with a device that has serial_number attr
        coordinator = mock_config_entry.runtime_data
        mock_device = MagicMock()
        mock_device.serial = None
        mock_device.serial_number = "AUTOMOWER-SN"
        coordinator.data = {"dev-1": mock_device}

        device_reg = dr.async_get(hass)
        device_entry = device_reg.async_get_or_create(
            config_entry_id=mock_config_entry.entry_id,
            identifiers={(DOMAIN, "AUTOMOWER-SN")},
        )

        result = await async_remove_config_entry_device(hass, mock_config_entry, device_entry)
        assert result is False


class TestAsyncMigrateEntry:
    """Test config entry migration."""

    async def test_v1_to_v2_adds_api_type(self, hass: HomeAssistant) -> None:
        """v1 entries get api_type=gardena added."""
        from custom_components.gardena_smart_system import async_migrate_entry

        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                CONF_CLIENT_ID: MOCK_CLIENT_ID,
                CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET,
                CONF_LOCATION_ID: MOCK_LOCATION_ID,
            },
            version=1,
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.data[CONF_API_TYPE] == API_TYPE_GARDENA
        assert entry.version == 2

    async def test_v2_entry_is_not_modified(self, hass: HomeAssistant) -> None:
        """v2 entries are left untouched."""
        from custom_components.gardena_smart_system import async_migrate_entry

        entry = MockConfigEntry(
            domain=DOMAIN,
            data={**ENTRY_DATA, CONF_API_TYPE: API_TYPE_GARDENA},
            version=2,
        )
        entry.add_to_hass(hass)

        result = await async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 2
