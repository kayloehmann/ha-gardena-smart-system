"""Tests for the Gardena Smart System switch platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
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


class TestSwitchEntityCreation:
    """Test switch entity creation for power socket devices."""

    async def test_power_socket_switch_created(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("switch.my_sensor_power")
        assert state is not None

    async def test_no_switch_without_power_socket(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=True, has_power_socket=False)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        entity_reg = er.async_get(hass)
        switch_entities = [
            e for e in entity_reg.entities.values()
            if e.domain == "switch" and e.platform == "gardena_smart_system"
        ]
        assert len(switch_entities) == 0


class TestSwitchUniqueId:
    """Test switch unique ID."""

    async def test_power_socket_unique_id(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("switch.my_sensor_power")
        assert entry is not None
        assert entry.unique_id == "SN001_power_socket"


class TestSwitchTranslationKey:
    """Test switch translation key."""

    async def test_power_socket_translation_key(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        entity_reg = er.async_get(hass)
        entry = entity_reg.async_get("switch.my_sensor_power")
        assert entry is not None
        assert entry.translation_key == "power_socket"


class TestSwitchStateMapping:
    """Test switch state mapping from power socket activity."""

    async def test_off_state(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        device.power_socket.activity = "OFF"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("switch.my_sensor_power")
        assert state is not None
        assert state.state == STATE_OFF

    async def test_forever_on_state(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        device.power_socket.activity = "FOREVER_ON"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("switch.my_sensor_power")
        assert state is not None
        assert state.state == STATE_ON

    async def test_time_limited_on_state(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        device.power_socket.activity = "TIME_LIMITED_ON"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("switch.my_sensor_power")
        assert state is not None
        assert state.state == STATE_ON

    async def test_scheduled_on_state(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        device.power_socket.activity = "SCHEDULED_ON"
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("switch.my_sensor_power")
        assert state is not None
        assert state.state == STATE_ON


class TestSwitchCommands:
    """Test switch turn_on/turn_off/turn_on_for commands."""

    async def test_turn_on_sends_start_override(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            await hass.services.async_call(
                "switch", "turn_on",
                {"entity_id": "switch.my_sensor_power"},
                blocking=True,
            )

            mock_client.async_send_command.assert_called_once_with(
                service_id=device.power_socket.service_id,
                control_type="POWER_SOCKET_CONTROL",
                command="START_OVERRIDE",
            )

    async def test_turn_off_sends_stop_until_next_task(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        device.power_socket.activity = "FOREVER_ON"
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            await hass.services.async_call(
                "switch", "turn_off",
                {"entity_id": "switch.my_sensor_power"},
                blocking=True,
            )

            mock_client.async_send_command.assert_called_once_with(
                service_id=device.power_socket.service_id,
                control_type="POWER_SOCKET_CONTROL",
                command="STOP_UNTIL_NEXT_TASK",
            )

    async def test_turn_on_for_service(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            await hass.services.async_call(
                "gardena_smart_system", "turn_on_for",
                {"entity_id": "switch.my_sensor_power", "duration": 45},
                blocking=True,
            )

            mock_client.async_send_command.assert_called_once_with(
                service_id=device.power_socket.service_id,
                control_type="POWER_SOCKET_CONTROL",
                command="START_SECONDS_TO_OVERRIDE",
                seconds=2700,  # 45 * 60
            )


class TestSwitchErrorHandling:
    """Test error handling in switch commands."""

    async def test_auth_error_raises_ha_error(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        from aiogardenasmart.exceptions import GardenaAuthenticationError

        device = make_mock_device(has_sensor=False, has_power_socket=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            mock_client.async_send_command.side_effect = GardenaAuthenticationError(
                "token expired"
            )

            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "switch", "turn_on",
                    {"entity_id": "switch.my_sensor_power"},
                    blocking=True,
                )

    async def test_gardena_exception_raises_ha_error(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        from aiogardenasmart.exceptions import GardenaException

        device = make_mock_device(has_sensor=False, has_power_socket=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            mock_client.async_send_command.side_effect = GardenaException("API error")

            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "switch", "turn_on",
                    {"entity_id": "switch.my_sensor_power"},
                    blocking=True,
                )

    async def test_command_when_device_unavailable_is_skipped(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            # Remove the device from coordinator data
            coordinator = mock_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            # HA silently skips service calls on unavailable entities
            await hass.services.async_call(
                "switch", "turn_on",
                {"entity_id": "switch.my_sensor_power"},
                blocking=True,
            )

            # Verify no command was sent
            mock_client.async_send_command.assert_not_called()


class TestSwitchUnavailability:
    """Test switch unavailability."""

    async def test_switch_unavailable_when_device_offline(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        device.is_online = False
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            pass

        state = hass.states.get("switch.my_sensor_power")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE

    async def test_switch_unavailable_when_removed(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        devices = {device.device_id: device}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            state = hass.states.get("switch.my_sensor_power")
            assert state.state == STATE_OFF

            coordinator = mock_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

        state = hass.states.get("switch.my_sensor_power")
        assert state is not None
        assert state.state == STATE_UNAVAILABLE


class TestSwitchDynamicDevices:
    """Test dynamic switch device addition."""

    async def test_new_power_socket_added_dynamically(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        device1 = make_mock_device("dev-1", "SN001", "Sensor 1")
        devices = {"dev-1": device1}

        async for _ in _setup_with_devices(hass, mock_config_entry, devices):
            # No switch initially
            entity_reg = er.async_get(hass)
            switch_entities = [
                e for e in entity_reg.entities.values()
                if e.domain == "switch" and e.platform == "gardena_smart_system"
            ]
            assert len(switch_entities) == 0

            # Add power socket device
            device2 = make_mock_device(
                "dev-2", "SN002", "Smart Plug", has_sensor=False, has_power_socket=True
            )
            new_devices = {"dev-1": device1, "dev-2": device2}
            coordinator = mock_config_entry.runtime_data
            coordinator.async_set_updated_data(new_devices)
            await hass.async_block_till_done()

            state = hass.states.get("switch.smart_plug_power")
            assert state is not None
