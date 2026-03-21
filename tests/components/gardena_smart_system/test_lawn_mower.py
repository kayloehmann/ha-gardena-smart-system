"""Tests for the Gardena Smart System lawn mower platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.gardena_smart_system.const import DOMAIN

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


async def _setup_with_devices(hass, mock_config_entry, devices):
    """Set up the integration with given device map and yield mock client."""
    with (
        patch(_PATCH_CLIENT) as mock_client_cls,
        patch(_PATCH_AUTH),
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


class TestLawnMowerEntityCreation:
    """Test lawn mower entity creation."""

    async def test_mower_entity_created(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state is not None

    async def test_no_mower_without_mower_service(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=True, has_mower=False)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        entity_reg = er.async_get(hass)
        mower_entities = [
            e for e in entity_reg.entities.values()
            if e.domain == "lawn_mower" and e.platform == "gardena_smart_system"
        ]
        assert len(mower_entities) == 0


class TestLawnMowerUniqueId:
    """Test lawn mower unique ID."""

    async def test_mower_unique_id(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("lawn_mower.my_sensor")
        assert entry is not None
        assert entry.unique_id == "SN001_mower"


class TestLawnMowerTranslationKey:
    """Test lawn mower translation key."""

    async def test_mower_translation_key(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("lawn_mower.my_sensor")
        assert entry is not None
        assert entry.translation_key == "mower"


class TestLawnMowerActivityMapping:
    """Test mower activity to HA state mapping."""

    async def test_ok_cutting_maps_to_mowing(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_CUTTING"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state is not None
        assert state.state == "mowing"

    async def test_ok_cutting_timer_overridden_maps_to_mowing(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_CUTTING_TIMER_OVERRIDDEN"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state.state == "mowing"

    async def test_ok_searching_maps_to_mowing(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_SEARCHING"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state.state == "mowing"

    async def test_ok_leaving_maps_to_mowing(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_LEAVING"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state.state == "mowing"

    async def test_ok_charging_maps_to_docked(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_CHARGING"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state.state == "docked"

    async def test_parked_timer_maps_to_docked(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "PARKED_TIMER"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state.state == "docked"

    async def test_parked_park_selected_maps_to_docked(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "PARKED_PARK_SELECTED"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state.state == "docked"

    async def test_parked_autotimer_maps_to_docked(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "PARKED_AUTOTIMER"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state.state == "docked"

    async def test_parked_frost_maps_to_docked(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "PARKED_FROST"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state.state == "docked"

    async def test_paused_maps_to_paused(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "PAUSED"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state.state == "paused"

    async def test_paused_in_cs_maps_to_paused(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "PAUSED_IN_CS"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state.state == "paused"

    async def test_stopped_in_garden_maps_to_error(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "STOPPED_IN_GARDEN"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state.state == "error"

    async def test_error_state_overrides_activity(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_CUTTING"
        device.mower.state = "ERROR"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state.state == "error"

    async def test_unknown_activity_defaults_to_paused(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "SOME_UNKNOWN_ACTIVITY"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state.state == "paused"

    async def test_none_activity_defaults_to_paused(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = None
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state.state == "paused"


class TestLawnMowerCommands:
    """Test lawn mower start, dock, pause, override_schedule commands."""

    async def test_start_mowing_command(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            await hass.services.async_call(
                "lawn_mower", "start_mowing",
                {"entity_id": "lawn_mower.my_sensor"},
                blocking=True,
            )

            mock_client.async_send_command.assert_called_once_with(
                service_id=device.mower.service_id,
                control_type="MOWER_CONTROL",
                command="START_DONT_OVERRIDE",
            )

    async def test_dock_command(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_CUTTING"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            await hass.services.async_call(
                "lawn_mower", "dock",
                {"entity_id": "lawn_mower.my_sensor"},
                blocking=True,
            )

            mock_client.async_send_command.assert_called_once_with(
                service_id=device.mower.service_id,
                control_type="MOWER_CONTROL",
                command="PARK_UNTIL_NEXT_TASK",
            )

    async def test_pause_command(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_CUTTING"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            await hass.services.async_call(
                "lawn_mower", "pause",
                {"entity_id": "lawn_mower.my_sensor"},
                blocking=True,
            )

            mock_client.async_send_command.assert_called_once_with(
                service_id=device.mower.service_id,
                control_type="MOWER_CONTROL",
                command="PARK_UNTIL_FURTHER_NOTICE",
            )

    async def test_override_schedule_service(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            await hass.services.async_call(
                "gardena_smart_system", "override_schedule",
                {"entity_id": "lawn_mower.my_sensor", "duration": 120},
                blocking=True,
            )

            mock_client.async_send_command.assert_called_once_with(
                service_id=device.mower.service_id,
                control_type="MOWER_CONTROL",
                command="START_SECONDS_TO_OVERRIDE",
                seconds=7200,  # 120 * 60
            )


class TestLawnMowerErrorHandling:
    """Test error handling in lawn mower commands."""

    async def test_auth_error_raises_ha_error(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        from aiogardenasmart.exceptions import GardenaAuthenticationError

        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            mock_client.async_send_command.side_effect = GardenaAuthenticationError(
                "token expired"
            )

            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "lawn_mower", "start_mowing",
                    {"entity_id": "lawn_mower.my_sensor"},
                    blocking=True,
                )

    async def test_gardena_exception_raises_ha_error(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        from aiogardenasmart.exceptions import GardenaException

        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            mock_client.async_send_command.side_effect = GardenaException("API error")

            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "lawn_mower", "start_mowing",
                    {"entity_id": "lawn_mower.my_sensor"},
                    blocking=True,
                )

    async def test_command_when_device_unavailable_is_skipped(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            # Remove from coordinator
            coordinator = mock_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            # HA silently skips service calls on unavailable entities
            await hass.services.async_call(
                "lawn_mower", "start_mowing",
                {"entity_id": "lawn_mower.my_sensor"},
                blocking=True,
            )

            # Verify no command was sent
            mock_client.async_send_command.assert_not_called()


class TestLawnMowerUnavailability:
    """Test lawn mower unavailability."""

    async def test_mower_unavailable_when_device_offline(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.is_online = False
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE

    async def test_mower_unavailable_when_removed_from_coordinator(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            state = hass.states.get("lawn_mower.my_sensor")
            assert state is not None
            assert state.state != STATE_UNAVAILABLE

            coordinator = mock_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

        state = hass.states.get("lawn_mower.my_sensor")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE


class TestLawnMowerExtraStateAttributes:
    """Test extra_state_attributes exposing detailed Gardena API fields."""

    async def test_activity_exposed_as_attribute(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_CUTTING"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state is not None
        assert state.attributes["activity"] == "OK_CUTTING"

    async def test_battery_state_exposed_as_attribute(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.common.battery_state = "CHARGING"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state is not None
        assert state.attributes["battery_state"] == "CHARGING"

    async def test_last_error_code_exposed_as_attribute(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.last_error_code = "TRAPPED"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state is not None
        assert state.attributes["last_error_code"] == "TRAPPED"

    async def test_no_last_error_code_when_none(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.last_error_code = None
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state is not None
        assert "last_error_code" not in state.attributes

    async def test_all_attributes_present(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "PARKED_FROST"
        device.mower.state = "OK"
        device.mower.last_error_code = "COLLISION"
        device.common.battery_state = "LOW"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("lawn_mower.my_sensor")
        assert state is not None
        assert state.attributes["activity"] == "PARKED_FROST"
        assert state.attributes["last_error_code"] == "COLLISION"
        assert state.attributes["battery_state"] == "LOW"


class TestLawnMowerDynamicDevices:
    """Test dynamic lawn mower device addition."""

    async def test_new_mower_device_added_dynamically(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device1 = make_mock_device("dev-1", "SN001", "Sensor 1")
        devices = {"dev-1": device1}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            # No mower initially
            entity_reg = er.async_get(hass)
            mower_entities = [
                e for e in entity_reg.entities.values()
                if e.domain == "lawn_mower" and e.platform == "gardena_smart_system"
            ]
            assert len(mower_entities) == 0

            # Add mower device
            device2 = make_mock_device(
                "dev-2", "SN002", "SILENO", has_sensor=False, has_mower=True
            )
            new_devices = {"dev-1": device1, "dev-2": device2}
            coordinator = mock_config_entry.runtime_data
            coordinator.async_set_updated_data(new_devices)
            await hass.async_block_till_done()

            state = hass.states.get("lawn_mower.sileno")
            assert state is not None
