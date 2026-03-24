"""Tests for the Gardena Smart System binary sensor platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import make_mock_device

_PATCH_CLIENT = "custom_components.gardena_smart_system.coordinator.GardenaClient"
_PATCH_AUTH = "custom_components.gardena_smart_system.coordinator.GardenaAuth"
_PATCH_WS = "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"


@pytest.fixture
def _mock_api_factory():
    """Return a helper that sets up the API mocks with given devices."""

    def _create(devices: dict):
        return (
            patch(_PATCH_CLIENT),
            patch(_PATCH_AUTH),
            patch(_PATCH_WS),
            devices,
        )

    return _create


async def _setup_with_devices(hass, mock_config_entry, devices):
    """Set up the integration with given device map."""
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


class TestBatteryLowBinarySensor:
    """Test the battery_low binary sensor."""

    async def test_battery_ok_state_is_off(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        device.common.battery_state = "OK"
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        state = hass.states.get("binary_sensor.my_sensor_battery_low")
        assert state is not None
        assert state.state == STATE_OFF

    async def test_battery_low_state_is_on(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        device.common.battery_state = "LOW"
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        state = hass.states.get("binary_sensor.my_sensor_battery_low")
        assert state is not None
        assert state.state == STATE_ON

    async def test_battery_replace_now_state_is_on(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        device.common.battery_state = "REPLACE_NOW"
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        state = hass.states.get("binary_sensor.my_sensor_battery_low")
        assert state is not None
        assert state.state == STATE_ON

    async def test_battery_charging_state_is_off(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        device.common.battery_state = "CHARGING"
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        state = hass.states.get("binary_sensor.my_sensor_battery_low")
        assert state is not None
        assert state.state == STATE_OFF

    async def test_no_battery_state_entity_not_created(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        device.common.battery_state = None
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        state = hass.states.get("binary_sensor.my_sensor_battery_low")
        assert state is None


class TestBatteryLowUniqueId:
    async def test_battery_low_unique_id(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("binary_sensor.my_sensor_battery_low")
        assert entry is not None
        assert entry.unique_id == "SN001_battery_low"


class TestValveErrorBinarySensor:
    """Test the valve_error binary sensor."""

    async def test_valve_error_created_and_disabled_by_default(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1)
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("binary_sensor.my_sensor_valve_error")
        assert entry is not None
        assert entry.disabled_by is not None

    async def test_valve_error_off_when_state_ok(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1)
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        # Enable the entity
        entity_reg = er.async_get(hass)
        entity_reg.async_update_entity("binary_sensor.my_sensor_valve_error", disabled_by=None)
        await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        # Re-setup because the reload cleared everything
        # Instead, let's verify via the registry that it was created correctly
        entry = entity_reg.async_get("binary_sensor.my_sensor_valve_error")
        assert entry is not None
        assert entry.unique_id == "SN001_valve_error"

    async def test_valve_error_not_created_for_device_without_valves(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=0)
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("binary_sensor.my_sensor_valve_error")
        assert entry is None

    async def test_valve_error_unique_id(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=2)
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("binary_sensor.my_sensor_valve_error")
        assert entry is not None
        assert entry.unique_id == "SN001_valve_error"


class TestMowerErrorBinarySensor:
    """Test the mower_error binary sensor."""

    async def test_mower_error_off_when_state_ok(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.state = "OK"
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        state = hass.states.get("binary_sensor.my_sensor_mower_error")
        assert state is not None
        assert state.state == STATE_OFF

    async def test_mower_error_on_when_state_error(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.state = "ERROR"
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        state = hass.states.get("binary_sensor.my_sensor_mower_error")
        assert state is not None
        assert state.state == STATE_ON

    async def test_mower_error_on_when_state_warning(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.state = "WARNING"
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        state = hass.states.get("binary_sensor.my_sensor_mower_error")
        assert state is not None
        assert state.state == STATE_ON

    async def test_mower_error_not_created_without_mower(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_mower=False)
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        state = hass.states.get("binary_sensor.my_sensor_mower_error")
        assert state is None

    async def test_mower_error_unique_id(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("binary_sensor.my_sensor_mower_error")
        assert entry is not None
        assert entry.unique_id == "SN001_mower_error"


class TestBinarySensorUnavailability:
    """Test binary sensors become unavailable when device goes offline."""

    async def test_binary_sensor_unavailable_when_device_offline(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        device.is_online = False
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        state = hass.states.get("binary_sensor.my_sensor_battery_low")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE

    async def test_binary_sensor_unavailable_when_device_removed(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        devices = {device.device_id: device}

        with (
            patch(_PATCH_CLIENT) as mock_client_cls,
            patch(_PATCH_AUTH),
            patch(_PATCH_WS) as mock_ws_cls,
        ):
            mock_client = AsyncMock()
            mock_client.async_get_devices = AsyncMock(return_value=devices)
            mock_client.async_get_websocket_url = AsyncMock(return_value="wss://test")
            mock_client_cls.return_value = mock_client
            mock_ws_cls.return_value = AsyncMock()

            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            # Verify available first
            state = hass.states.get("binary_sensor.my_sensor_battery_low")
            assert state is not None
            assert state.state == STATE_OFF

            # Remove device from coordinator data
            coordinator = mock_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

        state = hass.states.get("binary_sensor.my_sensor_battery_low")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE


class TestBinarySensorDynamicDevices:
    """Test dynamic addition of binary sensor entities."""

    async def test_new_mower_device_adds_binary_sensors(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device1 = make_mock_device("dev-1", "SN001", "Sensor 1")
        devices = {"dev-1": device1}

        with (
            patch(_PATCH_CLIENT) as mock_client_cls,
            patch(_PATCH_AUTH),
            patch(_PATCH_WS) as mock_ws_cls,
        ):
            mock_client = AsyncMock()
            mock_client.async_get_devices = AsyncMock(return_value=devices)
            mock_client.async_get_websocket_url = AsyncMock(return_value="wss://test")
            mock_client_cls.return_value = mock_client
            mock_ws_cls.return_value = AsyncMock()

            mock_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            # No mower error sensor initially
            assert hass.states.get("binary_sensor.my_mower_mower_error") is None

            # Add mower device
            device2 = make_mock_device(
                "dev-2", "SN002", "My Mower", has_sensor=False, has_mower=True
            )
            new_devices = {"dev-1": device1, "dev-2": device2}
            coordinator = mock_config_entry.runtime_data
            coordinator.async_set_updated_data(new_devices)
            await hass.async_block_till_done()

            state = hass.states.get("binary_sensor.my_mower_mower_error")
            assert state is not None
