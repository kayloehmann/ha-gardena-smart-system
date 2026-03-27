"""Tests for the Gardena Smart System sensor platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import make_mock_device

_PATCH_CLIENT = "custom_components.gardena_smart_system.coordinator.GardenaClient"
_PATCH_AUTH = "custom_components.gardena_smart_system.coordinator.GardenaAuth"
_PATCH_WS = "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"


def _setup_mock_api(devices: dict) -> tuple:
    """Return context managers that patch the coordinator dependencies."""
    return (
        patch(_PATCH_CLIENT),
        patch(_PATCH_AUTH),
        patch(_PATCH_WS),
        devices,
    )


@pytest.fixture
def mock_sensor_api(mock_devices: dict) -> object:
    """Patch aiogardenasmart classes and return the mock client."""
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


async def _setup_integration(
    hass: HomeAssistant, mock_config_entry: object, mock_api: object
) -> None:
    """Set up the integration and wait for it to be ready."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()


class TestSensorEntityCreation:
    """Test sensor entities are created for the right device services."""

    async def test_battery_level_sensor_created(
        self, hass: HomeAssistant, mock_config_entry: object, mock_sensor_api: object
    ) -> None:
        await _setup_integration(hass, mock_config_entry, mock_sensor_api)

        state = hass.states.get("sensor.my_sensor_battery")
        assert state is not None
        assert state.state == "85"

    async def test_rf_link_level_sensor_created_but_disabled(
        self, hass: HomeAssistant, mock_config_entry: object, mock_sensor_api: object
    ) -> None:
        await _setup_integration(hass, mock_config_entry, mock_sensor_api)

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("sensor.my_sensor_signal_strength")
        assert entry is not None
        assert entry.disabled_by is not None

    async def test_soil_humidity_sensor_created(
        self, hass: HomeAssistant, mock_config_entry: object, mock_sensor_api: object
    ) -> None:
        await _setup_integration(hass, mock_config_entry, mock_sensor_api)

        state = hass.states.get("sensor.my_sensor_soil_moisture")
        assert state is not None
        assert state.state == "42"

    async def test_soil_temperature_sensor_created(
        self, hass: HomeAssistant, mock_config_entry: object, mock_sensor_api: object
    ) -> None:
        await _setup_integration(hass, mock_config_entry, mock_sensor_api)

        state = hass.states.get("sensor.my_sensor_soil_temperature")
        assert state is not None
        assert state.state == "18.5"

    async def test_ambient_temperature_sensor_created(
        self, hass: HomeAssistant, mock_config_entry: object, mock_sensor_api: object
    ) -> None:
        await _setup_integration(hass, mock_config_entry, mock_sensor_api)

        state = hass.states.get("sensor.my_sensor_ambient_temperature")
        assert state is not None
        assert state.state == "22.1"

    async def test_light_intensity_sensor_created(
        self, hass: HomeAssistant, mock_config_entry: object, mock_sensor_api: object
    ) -> None:
        await _setup_integration(hass, mock_config_entry, mock_sensor_api)

        state = hass.states.get("sensor.my_sensor_light_intensity")
        assert state is not None
        assert state.state == "15000"

    async def test_mower_operating_hours_created_but_disabled(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(
            "mower-dev", "SN-MOWER", "My Mower", has_sensor=False, has_mower=True
        )
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

            await _setup_integration(hass, mock_config_entry, mock_client)

        entity_reg = er.async_get(hass)
        # mower_operating_hours has translation name "Operating hours"
        # On "My Mower" device with has_mower=True, has_sensor=False:
        # battery_level -> sensor.my_mower_battery
        # rf_link_level -> sensor.my_mower_signal_strength (disabled)
        # mower_operating_hours -> sensor.my_mower_operating_hours (disabled)
        entry = entity_reg.async_get("sensor.my_mower_operating_hours")
        assert entry is not None
        assert entry.disabled_by is not None

    async def test_mower_activity_sensor_created(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(
            "mower-dev", "SN-MOWER", "My Mower", has_sensor=False, has_mower=True
        )
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

            await _setup_integration(hass, mock_config_entry, mock_client)

        state = hass.states.get("sensor.my_mower_mower_activity")
        assert state is not None
        assert state.state == "PARKED_PARK_SELECTED"

    async def test_mower_last_error_code_created_but_disabled(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(
            "mower-dev", "SN-MOWER", "My Mower", has_sensor=False, has_mower=True
        )
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

            await _setup_integration(hass, mock_config_entry, mock_client)

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("sensor.my_mower_last_error_code")
        assert entry is not None
        assert entry.disabled_by is not None

    async def test_mower_last_error_code_value(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(
            "mower-dev", "SN-MOWER", "My Mower", has_sensor=False, has_mower=True
        )
        device.mower.last_error_code = "TRAPPED"
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

            await _setup_integration(hass, mock_config_entry, mock_client)

            # Enable the disabled entity and reload within the mock context
            entity_reg = er.async_get(hass)
            entity_reg.async_update_entity("sensor.my_mower_last_error_code", disabled_by=None)
            await hass.config_entries.async_reload(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            state = hass.states.get("sensor.my_mower_last_error_code")
            assert state is not None
            assert state.state == "TRAPPED"

    async def test_mower_activity_not_created_without_mower(
        self, hass: HomeAssistant, mock_config_entry: object, mock_sensor_api: object
    ) -> None:
        await _setup_integration(hass, mock_config_entry, mock_sensor_api)

        # Default mock device has no mower
        assert hass.states.get("sensor.my_sensor_mower_activity") is None

    async def test_no_sensor_entities_for_device_without_sensor_service(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device("no-sensor-dev", "SN-NS", "No Sensor", has_sensor=False)
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

            await _setup_integration(hass, mock_config_entry, mock_client)

        # Soil sensors should not exist
        assert hass.states.get("sensor.no_sensor_soil_moisture") is None
        assert hass.states.get("sensor.no_sensor_soil_temperature") is None
        assert hass.states.get("sensor.no_sensor_ambient_temperature") is None
        assert hass.states.get("sensor.no_sensor_light_intensity") is None


class TestSensorUniqueIds:
    """Test sensor entity unique IDs."""

    async def test_battery_sensor_unique_id(
        self, hass: HomeAssistant, mock_config_entry: object, mock_sensor_api: object
    ) -> None:
        await _setup_integration(hass, mock_config_entry, mock_sensor_api)

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("sensor.my_sensor_battery")
        assert entry is not None
        assert entry.unique_id == "SN001_battery_level"

    async def test_soil_humidity_unique_id(
        self, hass: HomeAssistant, mock_config_entry: object, mock_sensor_api: object
    ) -> None:
        await _setup_integration(hass, mock_config_entry, mock_sensor_api)

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("sensor.my_sensor_soil_moisture")
        assert entry is not None, "sensor.my_sensor_soil_moisture not found"
        assert entry.unique_id == "SN001_soil_humidity"


class TestSensorDeviceInfo:
    """Test sensor entities are linked to the correct device."""

    async def test_sensor_device_info(
        self, hass: HomeAssistant, mock_config_entry: object, mock_sensor_api: object
    ) -> None:
        await _setup_integration(hass, mock_config_entry, mock_sensor_api)

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("sensor.my_sensor_battery")
        assert entry is not None
        assert entry.device_id is not None


class TestSensorUnavailability:
    """Test sensor entities become unavailable when device goes offline."""

    async def test_sensor_unavailable_when_device_offline(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        device.is_online = False
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

            await _setup_integration(hass, mock_config_entry, mock_client)

        state = hass.states.get("sensor.my_sensor_battery")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE

    async def test_sensor_unavailable_when_device_removed_from_coordinator(
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

            await _setup_integration(hass, mock_config_entry, mock_client)

            # Verify sensor is available first
            state = hass.states.get("sensor.my_sensor_battery")
            assert state is not None
            assert state.state == "85"

            # Simulate device removal via coordinator data update
            coordinator = mock_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

        state = hass.states.get("sensor.my_sensor_battery")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE

    async def test_sensor_returns_none_when_service_value_missing(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device()
        device.sensor.soil_humidity = None
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

            await _setup_integration(hass, mock_config_entry, mock_client)

        # soil_humidity was set to None, but exists_fn checks is not None,
        # so the entity should not be created
        state = hass.states.get("sensor.my_sensor_soil_moisture")
        assert state is None

    async def test_logs_device_offline_and_online_transitions(
        self, hass: HomeAssistant, mock_config_entry: object, caplog: object
    ) -> None:
        """Test that device availability transitions are logged."""
        import logging

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

            await _setup_integration(hass, mock_config_entry, mock_client)

            # Device starts online — no log yet (first check, _was_available is None)
            state = hass.states.get("sensor.my_sensor_battery")
            assert state.state == "85"

            # Simulate device going offline
            device.is_online = False
            coordinator = mock_config_entry.runtime_data
            coordinator.async_set_updated_data(devices)
            await hass.async_block_till_done()

            state = hass.states.get("sensor.my_sensor_battery")
            assert state.state == STATE_UNAVAILABLE

            assert any(
                "Device My Sensor is offline" in r.message and r.levelno == logging.WARNING
                for r in caplog.records
            )

            # Simulate device coming back online
            caplog.clear()
            device.is_online = True
            coordinator.async_set_updated_data(devices)
            await hass.async_block_till_done()

            state = hass.states.get("sensor.my_sensor_battery")
            assert state.state == "85"

            assert any(
                "Device My Sensor is back online" in r.message and r.levelno == logging.INFO
                for r in caplog.records
            )


class TestSensorDynamicDevices:
    """Test new sensor entities are added when new devices appear."""

    async def test_new_sensor_device_added_dynamically(
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

            await _setup_integration(hass, mock_config_entry, mock_client)

            # Initially only one device
            assert hass.states.get("sensor.sensor_1_battery") is not None
            assert hass.states.get("sensor.sensor_2_battery") is None

            # Add a second device via coordinator update
            device2 = make_mock_device("dev-2", "SN002", "Sensor 2")
            new_devices = {"dev-1": device1, "dev-2": device2}
            coordinator = mock_config_entry.runtime_data
            coordinator.async_set_updated_data(new_devices)
            await hass.async_block_till_done()

            assert hass.states.get("sensor.sensor_2_battery") is not None


class TestValveErrorSensor:
    """Test per-valve error code sensors."""

    async def test_valve_error_sensor_created(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Per-valve error sensors are created for each valve."""
        device = make_mock_device(valve_count=2)
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

            await _setup_integration(hass, mock_config_entry, mock_client)

        entity_reg = er.async_get(hass)
        # Two valves: device-uuid:1 and device-uuid:2
        entry1 = entity_reg.async_get("sensor.my_sensor_valve_error_code")
        entry2 = entity_reg.async_get("sensor.my_sensor_valve_error_code_2")
        assert entry1 is not None
        assert entry2 is not None
        assert "valve_1_last_error_code" in entry1.unique_id
        assert "valve_2_last_error_code" in entry2.unique_id

    async def test_valve_error_sensor_disabled_by_default(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Valve error sensors are disabled by default."""
        device = make_mock_device(valve_count=1)
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

            await _setup_integration(hass, mock_config_entry, mock_client)

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("sensor.my_sensor_valve_error_code")
        assert entry is not None
        assert entry.disabled_by is not None

    async def test_valve_error_sensor_value(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Valve error sensor reports the last_error_code after enabling."""
        device = make_mock_device(valve_count=1)
        vid = f"{device.device_id}:1"
        device.valves[vid].last_error_code = "WATERING_CANCELED"
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

            await _setup_integration(hass, mock_config_entry, mock_client)

            entity_reg = er.async_get(hass)
            entity_reg.async_update_entity(
                "sensor.my_sensor_valve_error_code", disabled_by=None
            )
            await hass.config_entries.async_reload(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            state = hass.states.get("sensor.my_sensor_valve_error_code")
            assert state is not None
            assert state.state == "WATERING_CANCELED"

    async def test_valve_error_sensor_none_value(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Valve error sensor returns unknown when valve disappears."""
        device = make_mock_device(valve_count=1)
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

            await _setup_integration(hass, mock_config_entry, mock_client)

            entity_reg = er.async_get(hass)
            entity_reg.async_update_entity(
                "sensor.my_sensor_valve_error_code", disabled_by=None
            )
            await hass.config_entries.async_reload(mock_config_entry.entry_id)
            await hass.async_block_till_done()

            # Remove the device from coordinator → device gone → None
            coordinator = mock_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            state = hass.states.get("sensor.my_sensor_valve_error_code")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_no_valve_error_sensor_without_valves(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """No valve error sensors created for device without valves."""
        device = make_mock_device(valve_count=0)
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

            await _setup_integration(hass, mock_config_entry, mock_client)

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("sensor.my_sensor_valve_error_code")
        assert entry is None


class TestPowerSocketErrorSensor:
    """Test the power socket last error code sensor."""

    async def test_power_socket_error_sensor_created_disabled(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Power socket error sensor is created but disabled by default."""
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        device.power_socket.last_error_code = "NO_MESSAGE"
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

            await _setup_integration(hass, mock_config_entry, mock_client)

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("sensor.my_sensor_last_error_code")
        assert entry is not None
        assert entry.disabled_by is not None

    async def test_power_socket_error_sensor_not_created_without_socket(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """No power socket error sensor for device without power socket."""
        device = make_mock_device(has_power_socket=False)
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

            await _setup_integration(hass, mock_config_entry, mock_client)

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("sensor.my_sensor_last_error_code")
        assert entry is None


class TestSensorDeviceNoneGuard:
    """Test sensor native_value returns None when device disappears."""

    async def test_native_value_returns_none_when_device_gone(
        self, hass: HomeAssistant, mock_config_entry: object, mock_sensor_api: object
    ) -> None:
        """sensor.py:188-189: native_value returns None when device is None."""
        from custom_components.gardena_smart_system.sensor import (
            COMMON_SENSORS,
            GardenaSensorEntity,
        )

        await _setup_integration(hass, mock_config_entry, mock_sensor_api)

        coordinator = mock_config_entry.runtime_data
        # Get a device to construct the entity
        device = next(iter(coordinator.data.values()))
        coordinator.async_set_updated_data({})
        await hass.async_block_till_done()

        entity = GardenaSensorEntity(coordinator, device, COMMON_SENSORS[0])
        assert entity.native_value is None


# ──────────────────────────────────────────────────────────────────────
# Feature Tests: Valve Remaining Duration Sensor
# ──────────────────────────────────────────────────────────────────────


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


class TestValveRemainingDurationSensor:
    """Test the valve remaining duration sensor."""

    async def test_remaining_duration_sensor_created(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1)
        device.valves["device-uuid:1"].duration = 300
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        entity_reg = er.async_get(hass)
        # Find the entity by unique_id substring
        found = None
        for entry in entity_reg.entities.values():
            if "remaining_duration" in (entry.unique_id or ""):
                found = entry
                break
        assert found is not None

    async def test_remaining_duration_value_when_active(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1)
        device.valves["device-uuid:1"].duration = 300
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        entity_reg = er.async_get(hass)
        for entry in entity_reg.entities.values():
            if "remaining_duration" in (entry.unique_id or ""):
                state = hass.states.get(entry.entity_id)
                assert state is not None
                assert state.state == "300"
                break

    async def test_remaining_duration_none_when_zero(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1)
        device.valves["device-uuid:1"].duration = 0
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        entity_reg = er.async_get(hass)
        for entry in entity_reg.entities.values():
            if "remaining_duration" in (entry.unique_id or ""):
                state = hass.states.get(entry.entity_id)
                assert state is not None
                assert state.state == "unknown"
                break

    async def test_remaining_duration_none_when_duration_is_none(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1)
        device.valves["device-uuid:1"].duration = None
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        entity_reg = er.async_get(hass)
        for entry in entity_reg.entities.values():
            if "remaining_duration" in (entry.unique_id or ""):
                state = hass.states.get(entry.entity_id)
                assert state is not None
                assert state.state == "unknown"
                break

    async def test_no_remaining_duration_without_valves(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=0)
        await _setup_with_devices(hass, mock_config_entry, {device.device_id: device})

        entity_reg = er.async_get(hass)
        found = False
        for entry in entity_reg.entities.values():
            if "remaining_duration" in (entry.unique_id or ""):
                found = True
                break
        assert not found
