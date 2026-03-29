"""Tests for the Gardena Smart System valve platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.gardena_smart_system.const import (
    DOMAIN,
    OPT_DEFAULT_WATERING_MINUTES,
)

from .conftest import ENTRY_DATA, MOCK_LOCATION_NAME, make_mock_device

_PATCH_CLIENT = "custom_components.gardena_smart_system.coordinator.GardenaClient"
_PATCH_AUTH = "custom_components.gardena_smart_system.coordinator.GardenaAuth"
_PATCH_WS = "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"


async def _setup_with_devices(hass, mock_config_entry, devices):
    """Set up the integration with given device map and return the mock client."""
    with (
        patch(_PATCH_CLIENT) as mock_client_cls,
        patch(_PATCH_AUTH, return_value=AsyncMock()),
        patch(_PATCH_WS) as mock_ws_cls,
    ):
        mock_client = AsyncMock()
        mock_client.async_get_devices = AsyncMock(return_value=devices)
        mock_client.async_get_websocket_url = AsyncMock(return_value="wss://test")
        mock_client.async_send_command = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_ws = AsyncMock()
        mock_ws.async_connect = AsyncMock()
        mock_ws.async_disconnect = AsyncMock()
        mock_ws_cls.return_value = mock_ws

        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        yield mock_client


class TestValveEntityCreation:
    """Test valve entity creation."""

    async def test_single_valve_created(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1, has_sensor=False)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("valve.my_sensor_valve_1")
        assert state is not None

    async def test_multi_valve_device_creates_multiple_entities(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=3, has_sensor=False)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        # With valve_count=3, service IDs are device-uuid:1, device-uuid:2, device-uuid:3
        entity_reg = er.async_get(hass)
        valve_entities = [
            e
            for e in entity_reg.entities.values()
            if e.domain == "valve" and e.platform == "gardena_smart_system"
        ]
        assert len(valve_entities) == 3

    async def test_no_valve_without_valve_service(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=0)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        entity_reg = er.async_get(hass)
        valve_entities = [
            e
            for e in entity_reg.entities.values()
            if e.domain == "valve" and e.platform == "gardena_smart_system"
        ]
        assert len(valve_entities) == 0


class TestValveUniqueIds:
    """Test valve entity unique IDs."""

    async def test_valve_unique_id_uses_serial_and_index(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=2, has_sensor=False)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        entity_reg = er.async_get(hass)
        valve_entities = sorted(
            [
                e
                for e in entity_reg.entities.values()
                if e.domain == "valve" and e.platform == "gardena_smart_system"
            ],
            key=lambda e: e.unique_id,
        )
        assert len(valve_entities) == 2
        assert valve_entities[0].unique_id == "SN001_valve_1"
        assert valve_entities[1].unique_id == "SN001_valve_2"


class TestValveNaming:
    """Test valve entity naming uses zone names from the API."""

    async def test_valve_uses_api_zone_name(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1, has_sensor=False)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("valve.my_sensor_valve_1")
        assert state is not None
        assert state.attributes["friendly_name"] == "My Sensor Valve 1"

    async def test_multi_valve_has_distinct_names(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=3, has_sensor=False)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        for i in range(1, 4):
            state = hass.states.get(f"valve.my_sensor_valve_{i}")
            assert state is not None
            assert state.attributes["friendly_name"] == f"My Sensor Valve {i}"

    async def test_valve_falls_back_to_translation_key_when_no_name(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1, has_sensor=False)
        # Clear the valve name to trigger fallback
        valve_id = next(iter(device.valves.keys()))
        device.valves[valve_id].name = None
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        entity_reg = er.async_get(hass)
        valve_entities = [
            e
            for e in entity_reg.entities.values()
            if e.domain == "valve" and e.platform == "gardena_smart_system"
        ]
        assert len(valve_entities) == 1
        assert valve_entities[0].translation_key == "valve"


class TestValveStateMapping:
    """Test valve state mapping from API activity to HA state."""

    async def test_closed_valve_state(self, hass: HomeAssistant, mock_config_entry: object) -> None:
        device = make_mock_device(valve_count=1, has_sensor=False)
        # Default activity is "CLOSED"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("valve.my_sensor_valve_1")
        assert state is not None
        assert state.state == "closed"

    async def test_manual_watering_valve_is_open(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1, has_sensor=False)
        valve_id = next(iter(device.valves.keys()))
        device.valves[valve_id].activity = "MANUAL_WATERING"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("valve.my_sensor_valve_1")
        assert state is not None
        assert state.state == "open"

    async def test_scheduled_watering_valve_is_open(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1, has_sensor=False)
        valve_id = next(iter(device.valves.keys()))
        device.valves[valve_id].activity = "SCHEDULED_WATERING"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("valve.my_sensor_valve_1")
        assert state is not None
        assert state.state == "open"


class TestValveCommands:
    """Test valve open/close/start_watering commands."""

    async def test_open_valve_sends_start_command_with_default_duration(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1, has_sensor=False)
        valve_id = next(iter(device.valves.keys()))
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            await hass.services.async_call(
                "valve",
                "open_valve",
                {"entity_id": "valve.my_sensor_valve_1"},
                blocking=True,
            )

            mock_client.async_send_command.assert_called_once_with(
                service_id=valve_id,
                control_type="VALVE_CONTROL",
                command="START_SECONDS_TO_OVERRIDE",
                seconds=3600,  # 60 minutes default * 60
            )

    async def test_close_valve_sends_stop_command(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1, has_sensor=False)
        valve_id = next(iter(device.valves.keys()))
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            await hass.services.async_call(
                "valve",
                "close_valve",
                {"entity_id": "valve.my_sensor_valve_1"},
                blocking=True,
            )

            mock_client.async_send_command.assert_called_once_with(
                service_id=valve_id,
                control_type="VALVE_CONTROL",
                command="STOP_UNTIL_NEXT_TASK",
            )

    async def test_start_watering_service(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1, has_sensor=False)
        valve_id = next(iter(device.valves.keys()))
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            await hass.services.async_call(
                "gardena_smart_system",
                "start_watering",
                {"entity_id": "valve.my_sensor_valve_1", "duration": 30},
                blocking=True,
            )

            mock_client.async_send_command.assert_called_once_with(
                service_id=valve_id,
                control_type="VALVE_CONTROL",
                command="START_SECONDS_TO_OVERRIDE",
                seconds=1800,  # 30 minutes * 60
            )


class TestValveErrorHandling:
    """Test error handling in valve commands."""

    async def test_auth_error_triggers_reauth(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        from aiogardenasmart.exceptions import GardenaAuthenticationError

        device = make_mock_device(valve_count=1, has_sensor=False)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            mock_client.async_send_command.side_effect = GardenaAuthenticationError("token expired")

            # ConfigEntryAuthFailed is caught by HA and triggers reauth flow,
            # but at the service call level it manifests as HomeAssistantError
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "valve",
                    "open_valve",
                    {"entity_id": "valve.my_sensor_valve_1"},
                    blocking=True,
                )

    async def test_gardena_exception_raises_ha_error(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        from aiogardenasmart.exceptions import GardenaException

        device = make_mock_device(valve_count=1, has_sensor=False)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            mock_client.async_send_command.side_effect = GardenaException("API error")

            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "valve",
                    "open_valve",
                    {"entity_id": "valve.my_sensor_valve_1"},
                    blocking=True,
                )


class TestValveUnavailability:
    """Test valve unavailability."""

    async def test_valve_unavailable_when_device_offline(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1, has_sensor=False)
        device.is_online = False
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("valve.my_sensor_valve_1")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE

    async def test_valve_unavailable_when_removed_from_coordinator(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(valve_count=1, has_sensor=False)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            # Verify valve is available first
            state = hass.states.get("valve.my_sensor_valve_1")
            assert state is not None
            assert state.state == "closed"

            # Remove from coordinator
            coordinator = mock_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

        state = hass.states.get("valve.my_sensor_valve_1")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE


class TestValveDynamicDevices:
    """Test dynamic valve device addition."""

    async def test_new_valve_device_added_dynamically(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device1 = make_mock_device("dev-1", "SN001", "Sensor 1")
        devices = {"dev-1": device1}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            # No valve entities initially
            entity_reg = er.async_get(hass)
            valve_entities = [
                e
                for e in entity_reg.entities.values()
                if e.domain == "valve" and e.platform == "gardena_smart_system"
            ]
            assert len(valve_entities) == 0

            # Add a valve device
            device2 = make_mock_device(
                "dev-2", "SN002", "Irrigation", has_sensor=False, valve_count=2
            )
            new_devices = {"dev-1": device1, "dev-2": device2}
            coordinator = mock_config_entry.runtime_data
            coordinator.async_set_updated_data(new_devices)
            await hass.async_block_till_done()

            valve_entities = [
                e
                for e in entity_reg.entities.values()
                if e.domain == "valve" and e.platform == "gardena_smart_system"
            ]
            assert len(valve_entities) == 2


class TestValveOptionsIntegration:
    """Test that valve commands use configured options."""

    async def test_open_valve_uses_configured_duration(self, hass: HomeAssistant) -> None:
        try:
            from tests.common import MockConfigEntry
        except ImportError:
            from pytest_homeassistant_custom_component.common import (
                MockConfigEntry,  # type: ignore[no-redef]
            )

        entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            title=MOCK_LOCATION_NAME,
            options={OPT_DEFAULT_WATERING_MINUTES: 30},
        )

        device = make_mock_device(valve_count=1, has_sensor=False)
        valve_id = next(iter(device.valves.keys()))
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, entry, devices):
            await hass.services.async_call(
                "valve",
                "open_valve",
                {"entity_id": "valve.my_sensor_valve_1"},
                blocking=True,
            )

            mock_client.async_send_command.assert_called_once_with(
                service_id=valve_id,
                control_type="VALVE_CONTROL",
                command="START_SECONDS_TO_OVERRIDE",
                seconds=1800,  # 30 minutes * 60
            )


class TestValveDeviceNoneGuards:
    """Test property guards when the device is removed from coordinator data."""

    async def test_valve_property_returns_none_when_device_gone(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        from custom_components.gardena_smart_system.valve import GardenaValveEntity

        device = make_mock_device(valve_count=1, has_sensor=False)
        valve_id = next(iter(device.valves.keys()))
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            coordinator = mock_config_entry.runtime_data
            entity = GardenaValveEntity(coordinator, device, valve_id)

            coordinator.async_set_updated_data({})
            assert entity._valve is None

    async def test_is_closed_returns_none_when_device_gone(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        from custom_components.gardena_smart_system.valve import GardenaValveEntity

        device = make_mock_device(valve_count=1, has_sensor=False)
        valve_id = next(iter(device.valves.keys()))
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            coordinator = mock_config_entry.runtime_data
            entity = GardenaValveEntity(coordinator, device, valve_id)

            coordinator.async_set_updated_data({})
            assert entity.is_closed is None

    async def test_extra_state_attributes_returns_none_when_device_gone(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        from custom_components.gardena_smart_system.valve import GardenaValveEntity

        device = make_mock_device(valve_count=1, has_sensor=False)
        valve_id = next(iter(device.valves.keys()))
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            coordinator = mock_config_entry.runtime_data
            entity = GardenaValveEntity(coordinator, device, valve_id)

            coordinator.async_set_updated_data({})
            assert entity.extra_state_attributes is None

    async def test_send_command_raises_when_device_gone(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        from custom_components.gardena_smart_system.valve import GardenaValveEntity

        device = make_mock_device(valve_count=1, has_sensor=False)
        valve_id = next(iter(device.valves.keys()))
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            coordinator = mock_config_entry.runtime_data
            entity = GardenaValveEntity(coordinator, device, valve_id)

            coordinator.async_set_updated_data({})
            with pytest.raises(HomeAssistantError):
                await entity._async_send_command("START_SECONDS_TO_OVERRIDE", seconds=60)
