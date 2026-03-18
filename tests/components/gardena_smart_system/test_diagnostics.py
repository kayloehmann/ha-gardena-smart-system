"""Tests for the Gardena Smart System diagnostics."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.gardena_smart_system.const import DOMAIN
from custom_components.gardena_smart_system.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)

from .conftest import ENTRY_DATA, make_mock_device

_PATCH_CLIENT = (
    "custom_components.gardena_smart_system.coordinator.GardenaClient"
)
_PATCH_AUTH = (
    "custom_components.gardena_smart_system.coordinator.GardenaAuth"
)
_PATCH_WS = (
    "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"
)


async def _setup_integration(hass, mock_config_entry, devices):
    """Set up the integration with given devices."""
    with (
        patch(_PATCH_CLIENT) as mock_client_cls,
        patch(_PATCH_AUTH),
        patch(_PATCH_WS) as mock_ws_cls,
    ):
        mock_client = AsyncMock()
        mock_client.async_get_devices = AsyncMock(return_value=devices)
        mock_client.async_get_websocket_url = AsyncMock(return_value="wss://test")
        mock_client_cls.return_value = mock_client
        mock_ws = AsyncMock()
        mock_ws.async_connect = AsyncMock()
        mock_ws.async_disconnect = AsyncMock()
        mock_ws_cls.return_value = mock_ws

        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        yield


class TestDiagnosticsOutput:
    """Test diagnostics data structure and content."""

    async def test_diagnostics_returns_device_data(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        devices = {device.device_id: device}

        async for _ in _setup_integration(hass, mock_config_entry, devices):
            result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        assert "config_entry" in result
        assert "devices" in result
        assert len(result["devices"]) == 1

    async def test_diagnostics_contains_device_fields(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        devices = {device.device_id: device}

        async for _ in _setup_integration(hass, mock_config_entry, devices):
            result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        device_data = result["devices"][device.device_id]
        assert "name" in device_data
        assert "model" in device_data
        assert "is_online" in device_data
        assert "common" in device_data
        assert "mower" in device_data
        assert "sensor" in device_data
        assert "power_socket" in device_data
        assert "valve_set" in device_data
        assert "valves" in device_data

    async def test_diagnostics_with_mower_device(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for _ in _setup_integration(hass, mock_config_entry, devices):
            result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        device_data = result["devices"][device.device_id]
        assert device_data["mower"] is not None
        assert device_data["sensor"] is None

    async def test_diagnostics_with_valve_device(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, valve_count=2)
        devices = {device.device_id: device}

        async for _ in _setup_integration(hass, mock_config_entry, devices):
            result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        device_data = result["devices"][device.device_id]
        assert len(device_data["valves"]) == 2

    async def test_diagnostics_with_power_socket(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        devices = {device.device_id: device}

        async for _ in _setup_integration(hass, mock_config_entry, devices):
            result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        device_data = result["devices"][device.device_id]
        assert device_data["power_socket"] is not None

    async def test_diagnostics_with_no_devices(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        devices: dict = {}

        async for _ in _setup_integration(hass, mock_config_entry, devices):
            result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        assert result["devices"] == {}

    async def test_diagnostics_config_entry_included(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        devices = {device.device_id: device}

        async for _ in _setup_integration(hass, mock_config_entry, devices):
            result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        assert "config_entry" in result
        # The config entry should be a dict from as_dict()
        assert isinstance(result["config_entry"], dict)


class TestDiagnosticsRedaction:
    """Test that sensitive data is redacted."""

    async def test_redaction_keys_defined(self) -> None:
        """Verify the TO_REDACT set covers sensitive fields."""
        assert "client_id" in TO_REDACT
        assert "client_secret" in TO_REDACT
        assert "serial" in TO_REDACT
        assert "location_id" in TO_REDACT

    async def test_client_id_redacted_in_output(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        devices = {device.device_id: device}

        async for _ in _setup_integration(hass, mock_config_entry, devices):
            result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        # The config entry data should have client_id and client_secret redacted
        config_data = result["config_entry"]["data"]
        assert config_data["client_id"] == "**REDACTED**"
        assert config_data["client_secret"] == "**REDACTED**"

    async def test_location_id_redacted(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        devices = {device.device_id: device}

        async for _ in _setup_integration(hass, mock_config_entry, devices):
            result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        config_data = result["config_entry"]["data"]
        assert config_data["location_id"] == "**REDACTED**"


class TestDiagnosticsServiceToDict:
    """Test the _service_to_dict helper function."""

    async def test_none_service_returns_none(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=False)
        devices = {device.device_id: device}

        async for _ in _setup_integration(hass, mock_config_entry, devices):
            result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        device_data = result["devices"][device.device_id]
        assert device_data["mower"] is None
        assert device_data["sensor"] is None

    async def test_service_to_dict_contains_attributes(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        devices = {device.device_id: device}

        async for _ in _setup_integration(hass, mock_config_entry, devices):
            result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

        device_data = result["devices"][device.device_id]
        common = device_data["common"]
        assert common is not None
        # MagicMock vars() will have internal mock attributes but the function
        # still should return a dict
        assert isinstance(common, dict)
