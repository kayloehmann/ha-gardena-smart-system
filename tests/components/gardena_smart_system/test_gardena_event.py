"""Tests for the Gardena event platform (gardena_event.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import make_mock_device

_PATCH_CLIENT = "custom_components.gardena_smart_system.coordinator.GardenaClient"
_PATCH_AUTH = "custom_components.gardena_smart_system.coordinator.GardenaAuth"
_PATCH_WS = "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"


async def _setup_with_devices_ctx(hass, mock_config_entry, devices):
    """Set up the integration keeping mock context active. Returns (mock_client, patches)."""
    patches = (
        patch(_PATCH_CLIENT),
        patch(_PATCH_AUTH, return_value=AsyncMock()),
        patch(_PATCH_WS),
    )
    p_client = patches[0].__enter__()
    patches[1].__enter__()
    p_ws = patches[2].__enter__()

    mock_client = AsyncMock()
    mock_client.async_get_devices = AsyncMock(return_value=devices)
    mock_client.async_get_websocket_url = AsyncMock(return_value="wss://test")
    p_client.return_value = mock_client

    mock_ws = AsyncMock()
    mock_ws.async_connect = AsyncMock()
    mock_ws.async_disconnect = AsyncMock()
    p_ws.return_value = mock_ws

    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    return mock_client, patches


def _copy_device(device: MagicMock, **overrides) -> MagicMock:
    """Return a shallow copy of a device mock with specific attributes overridden."""
    new = MagicMock()
    new.device_id = device.device_id
    new.serial = device.serial
    new.serial_number = device.serial_number
    new.name = device.name
    new.is_online = device.is_online
    new.common = device.common
    new.model = device.model
    new.sensor = device.sensor
    new.mower = device.mower
    new.power_socket = device.power_socket
    new.valves = dict(device.valves)
    new.valve_set = device.valve_set
    for k, v in overrides.items():
        setattr(new, k, v)
    return new


class TestGardenaMowerEvent:
    """Test the mower event entity (GardenaMowerEventEntity)."""

    async def test_mower_event_entity_created(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Mower event entity is created for a device with a mower."""
        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            entity_reg = er.async_get(hass)
            entries = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system" and e.domain == "event"
            ]
            assert len(entries) >= 1
            assert any("mower_event" in (e.unique_id or "") for e in entries)
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_mower_event_not_created_without_mower(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """No mower event entity for device without mower."""
        device = make_mock_device(has_mower=False)
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            entity_reg = er.async_get(hass)
            entries = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "mower" in (e.unique_id or "")
            ]
            assert len(entries) == 0
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_mower_event_started_cutting(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Mower event fires started_cutting on activity change."""
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "PARKED_PARK_SELECTED"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data

            # Change mower activity to cutting
            updated = _copy_device(device)
            updated.mower = MagicMock()
            updated.mower.activity = "OK_CUTTING"
            updated.mower.state = "OK"
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            # Find the event entity
            entity_reg = er.async_get(hass)
            event_entries = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "mower_event" in (e.unique_id or "")
            ]
            assert len(event_entries) == 1
            state = hass.states.get(event_entries[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "started_cutting"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_mower_event_error(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Mower event fires error when state transitions to ERROR."""
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_CUTTING"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data

            updated = _copy_device(device)
            updated.mower = MagicMock()
            updated.mower.activity = "STOPPED_IN_GARDEN"
            updated.mower.state = "ERROR"
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            event_entries = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "mower_event" in (e.unique_id or "")
            ]
            state = hass.states.get(event_entries[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "error"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_mower_event_error_cleared(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Mower event fires error_cleared when leaving error state."""
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "STOPPED_IN_GARDEN"
        device.mower.state = "ERROR"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data

            updated = _copy_device(device)
            updated.mower = MagicMock()
            updated.mower.activity = "OK_CHARGING"
            updated.mower.state = "OK"
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            event_entries = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "mower_event" in (e.unique_id or "")
            ]
            state = hass.states.get(event_entries[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "error_cleared"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_mower_event_parked(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Mower event fires parked on parking activity."""
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_CUTTING"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data

            updated = _copy_device(device)
            updated.mower = MagicMock()
            updated.mower.activity = "PARKED_TIMER"
            updated.mower.state = "OK"
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            event_entries = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "mower_event" in (e.unique_id or "")
            ]
            state = hass.states.get(event_entries[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "parked"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)


class TestGardenaValveEvent:
    """Test the valve event entity (GardenaValveEventEntity)."""

    async def test_valve_event_entity_created(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Valve event entity is created for each valve."""
        device = make_mock_device(valve_count=2, has_sensor=False)
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            entity_reg = er.async_get(hass)
            valve_events = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "valve" in (e.unique_id or "")
            ]
            assert len(valve_events) == 2
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_valve_event_started_watering(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Valve event fires started_watering on activity change."""
        device = make_mock_device(valve_count=1, has_sensor=False)
        vid = f"{device.device_id}:1"
        device.valves[vid].activity = "CLOSED"
        device.valves[vid].state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data

            updated = _copy_device(device)
            new_valve = MagicMock()
            new_valve.activity = "MANUAL_WATERING"
            new_valve.state = "OK"
            new_valve.service_id = vid
            new_valve.name = "Valve 1"
            new_valve.duration = None
            new_valve.last_error_code = None
            updated.valves = {vid: new_valve}
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            valve_events = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "valve" in (e.unique_id or "")
            ]
            assert len(valve_events) == 1
            state = hass.states.get(valve_events[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "started_watering"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_valve_event_stopped_watering(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Valve event fires stopped_watering when valve closes."""
        device = make_mock_device(valve_count=1, has_sensor=False)
        vid = f"{device.device_id}:1"
        device.valves[vid].activity = "MANUAL_WATERING"
        device.valves[vid].state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data

            updated = _copy_device(device)
            new_valve = MagicMock()
            new_valve.activity = "CLOSED"
            new_valve.state = "OK"
            new_valve.service_id = vid
            new_valve.name = "Valve 1"
            new_valve.duration = None
            new_valve.last_error_code = None
            updated.valves = {vid: new_valve}
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            valve_events = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "valve" in (e.unique_id or "")
            ]
            state = hass.states.get(valve_events[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "stopped_watering"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_valve_event_error(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Valve event fires error on state transition to ERROR."""
        device = make_mock_device(valve_count=1, has_sensor=False)
        vid = f"{device.device_id}:1"
        device.valves[vid].activity = "CLOSED"
        device.valves[vid].state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data

            updated = _copy_device(device)
            new_valve = MagicMock()
            new_valve.activity = "CLOSED"
            new_valve.state = "ERROR"
            new_valve.service_id = vid
            new_valve.name = "Valve 1"
            new_valve.duration = None
            new_valve.last_error_code = None
            updated.valves = {vid: new_valve}
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            valve_events = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "valve" in (e.unique_id or "")
            ]
            state = hass.states.get(valve_events[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "error"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)


class TestGardenaPowerSocketEvent:
    """Test the power socket event entity (GardenaPowerSocketEventEntity)."""

    async def test_power_socket_event_entity_created(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Power socket event entity is created."""
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            entity_reg = er.async_get(hass)
            ps_events = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "power_socket_event" in (e.unique_id or "")
            ]
            assert len(ps_events) == 1
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_power_socket_event_turned_on(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Power socket event fires turned_on."""
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        device.power_socket.activity = "OFF"
        device.power_socket.state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data

            updated = _copy_device(device)
            updated.power_socket = MagicMock()
            updated.power_socket.activity = "FOREVER_ON"
            updated.power_socket.state = "OK"
            updated.power_socket.duration = None
            updated.power_socket.last_error_code = None
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            ps_events = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "power_socket_event" in (e.unique_id or "")
            ]
            state = hass.states.get(ps_events[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "turned_on"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_power_socket_event_turned_off(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Power socket event fires turned_off."""
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        device.power_socket.activity = "FOREVER_ON"
        device.power_socket.state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data

            updated = _copy_device(device)
            updated.power_socket = MagicMock()
            updated.power_socket.activity = "OFF"
            updated.power_socket.state = "OK"
            updated.power_socket.duration = None
            updated.power_socket.last_error_code = None
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            ps_events = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "power_socket_event" in (e.unique_id or "")
            ]
            state = hass.states.get(ps_events[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "turned_off"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_power_socket_event_not_created_without_socket(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """No power socket event entity for device without socket."""
        device = make_mock_device(has_power_socket=False)
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            entity_reg = er.async_get(hass)
            ps_events = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "power_socket_event" in (e.unique_id or "")
            ]
            assert len(ps_events) == 0
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_power_socket_event_error(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Power socket event fires error on state transition to ERROR."""
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        device.power_socket.activity = "FOREVER_ON"
        device.power_socket.state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data

            updated = _copy_device(device)
            updated.power_socket = MagicMock()
            updated.power_socket.activity = "FOREVER_ON"
            updated.power_socket.state = "ERROR"
            updated.power_socket.duration = None
            updated.power_socket.last_error_code = None
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            ps_events = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "power_socket_event" in (e.unique_id or "")
            ]
            state = hass.states.get(ps_events[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "error"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_power_socket_event_error_cleared(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Power socket event fires error_cleared when leaving error state."""
        device = make_mock_device(has_sensor=False, has_power_socket=True)
        device.power_socket.activity = "FOREVER_ON"
        device.power_socket.state = "ERROR"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data

            updated = _copy_device(device)
            updated.power_socket = MagicMock()
            updated.power_socket.activity = "FOREVER_ON"
            updated.power_socket.state = "OK"
            updated.power_socket.duration = None
            updated.power_socket.last_error_code = None
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            ps_events = [
                e
                for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system"
                and e.domain == "event"
                and "power_socket_event" in (e.unique_id or "")
            ]
            state = hass.states.get(ps_events[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "error_cleared"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)


class TestGardenaEventMowerTransitions:
    """Test remaining mower event transitions (leaving, searching, charging, paused, stopped)."""

    async def test_mower_event_leaving(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Mower event fires leaving on OK_LEAVING activity."""
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "PARKED_TIMER"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data
            updated = _copy_device(device)
            updated.mower = MagicMock()
            updated.mower.activity = "OK_LEAVING"
            updated.mower.state = "OK"
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            event_entries = [
                e for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system" and e.domain == "event"
                and "mower_event" in (e.unique_id or "")
            ]
            state = hass.states.get(event_entries[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "leaving"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_mower_event_searching(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Mower event fires searching on OK_SEARCHING activity."""
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_CUTTING"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data
            updated = _copy_device(device)
            updated.mower = MagicMock()
            updated.mower.activity = "OK_SEARCHING"
            updated.mower.state = "OK"
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            event_entries = [
                e for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system" and e.domain == "event"
                and "mower_event" in (e.unique_id or "")
            ]
            state = hass.states.get(event_entries[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "searching"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_mower_event_charging(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Mower event fires charging on OK_CHARGING activity."""
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_CUTTING"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data
            updated = _copy_device(device)
            updated.mower = MagicMock()
            updated.mower.activity = "OK_CHARGING"
            updated.mower.state = "OK"
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            event_entries = [
                e for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system" and e.domain == "event"
                and "mower_event" in (e.unique_id or "")
            ]
            state = hass.states.get(event_entries[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "charging"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_mower_event_paused(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Mower event fires paused on PAUSED activity."""
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_CUTTING"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data
            updated = _copy_device(device)
            updated.mower = MagicMock()
            updated.mower.activity = "PAUSED"
            updated.mower.state = "OK"
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            event_entries = [
                e for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system" and e.domain == "event"
                and "mower_event" in (e.unique_id or "")
            ]
            state = hass.states.get(event_entries[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "paused"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

    async def test_mower_event_stopped(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Mower event fires stopped on STOPPED_IN_GARDEN activity."""
        device = make_mock_device(has_sensor=False, has_mower=True)
        device.mower.activity = "OK_CUTTING"
        device.mower.state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data
            updated = _copy_device(device)
            updated.mower = MagicMock()
            updated.mower.activity = "STOPPED_IN_GARDEN"
            updated.mower.state = "OK"
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            event_entries = [
                e for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system" and e.domain == "event"
                and "mower_event" in (e.unique_id or "")
            ]
            state = hass.states.get(event_entries[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "stopped"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)


class TestGardenaValveEventErrorCleared:
    """Test valve error_cleared event."""

    async def test_valve_event_error_cleared(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Valve event fires error_cleared when leaving error state."""
        device = make_mock_device(valve_count=1, has_sensor=False)
        vid = f"{device.device_id}:1"
        device.valves[vid].activity = "CLOSED"
        device.valves[vid].state = "ERROR"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data

            updated = _copy_device(device)
            new_valve = MagicMock()
            new_valve.activity = "CLOSED"
            new_valve.state = "OK"
            new_valve.service_id = vid
            new_valve.name = "Valve 1"
            new_valve.duration = None
            new_valve.last_error_code = None
            updated.valves = {vid: new_valve}
            coordinator.async_set_updated_data({device.device_id: updated})
            await hass.async_block_till_done()

            entity_reg = er.async_get(hass)
            valve_events = [
                e for e in entity_reg.entities.values()
                if e.platform == "gardena_smart_system" and e.domain == "event"
                and "valve" in (e.unique_id or "")
            ]
            state = hass.states.get(valve_events[0].entity_id)
            assert state is not None
            assert state.attributes.get("event_type") == "error_cleared"
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)


class TestGardenaEventDeviceNone:
    """Test event entities handle device removal (coordinator.data missing device)."""

    async def test_valve_event_device_removed(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Valve event entity handles device removed from coordinator data."""
        device = make_mock_device(valve_count=1, has_sensor=False)
        vid = f"{device.device_id}:1"
        device.valves[vid].activity = "CLOSED"
        device.valves[vid].state = "OK"
        devices = {device.device_id: device}

        _mock_client, patches = await _setup_with_devices_ctx(
            hass, mock_config_entry, devices
        )
        try:
            coordinator = mock_config_entry.runtime_data
            # Remove device from coordinator data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()
            # Entity should not crash, just become unavailable
        finally:
            for p in reversed(patches):
                p.__exit__(None, None, None)

