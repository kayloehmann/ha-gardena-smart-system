"""Tests for Gardena Smart System integration setup and teardown."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.gardena_smart_system.const import DOMAIN

from .conftest import make_mock_device

_PATCH_CLIENT = (
    "custom_components.gardena_smart_system.coordinator.GardenaClient"
)
_PATCH_AUTH = (
    "custom_components.gardena_smart_system.coordinator.GardenaAuth"
)
_PATCH_WS = (
    "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"
)


@pytest.fixture
def mock_api(mock_devices: dict) -> object:
    """Patch all aiogardenasmart classes used by the coordinator."""
    with (
        patch(_PATCH_CLIENT) as mock_client_cls,
        patch(_PATCH_AUTH),
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

        with patch(_PATCH_CLIENT) as mock_cls, patch(_PATCH_AUTH):
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

        with patch(_PATCH_CLIENT) as mock_cls, patch(_PATCH_AUTH):
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
