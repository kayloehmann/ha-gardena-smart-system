"""Tests for the Automower integration components."""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import MockConfigEntry  # type: ignore[no-redef]

from aioautomower.const import HeadlightMode, MowerActivity, MowerState
from aioautomower.exceptions import (
    AutomowerAuthenticationError,
    AutomowerConnectionError,
    AutomowerException,
    AutomowerForbiddenError,
    AutomowerRateLimitError,
)
from aioautomower.models import (
    AutomowerDevice,
    BatteryInfo,
    CalendarInfo,
    CapabilitiesInfo,
    MetadataInfo,
    MowerInfo,
    PlannerInfo,
    PlannerOverride,
    Position,
    ScheduleTask,
    SettingsInfo,
    StatisticsInfo,
    StayOutZone,
    SystemInfo,
    WorkArea,
)

from custom_components.gardena_smart_system.const import DOMAIN

_PATCH_AM_CLIENT = (
    "custom_components.gardena_smart_system.automower_coordinator.AutomowerClient"
)
_PATCH_AM_AUTH = (
    "custom_components.gardena_smart_system.automower_coordinator.GardenaAuth"
)
_PATCH_AM_WS = (
    "custom_components.gardena_smart_system.automower_coordinator.AutomowerWebSocket"
)

AUTOMOWER_ENTRY_DATA: dict[str, str] = {
    "client_id": "test-client-id",
    "client_secret": "test-client-secret",
    "api_type": "automower",
}

# Entity IDs are derived from device name + translated entity name.
# With has_entity_name=True and device name "Test Mower":
#   - sensor with translation "Battery" -> sensor.test_mower_battery
#   - sensor with translation "Cutting height" -> sensor.test_mower_cutting_height
#   - sensor with translation "Next start" -> sensor.test_mower_next_start
#   - binary_sensor with translation "Error" -> binary_sensor.test_mower_error
#   - binary_sensor with translation "Connected" -> binary_sensor.test_mower_connected
#   - lawn_mower with translation "Mower" -> lawn_mower.test_mower_mower
#   - switch with translation "Headlight" -> switch.test_mower_headlight
#   - number with translation "Cutting height" -> number.test_mower_cutting_height
#   - device_tracker with translation "Position" -> device_tracker.test_mower_position
#   - calendar with translation "Mowing schedule" -> calendar.test_mower_mowing_schedule


def make_mock_automower_device(
    mower_id: str = "mower-uuid-1",
    name: str = "Test Mower",
    model: str = "HUSQVARNA AUTOMOWER 450XH",
    serial_number: str = "AM-SN-001",
    battery_level: int = 75,
    mower_mode: str = "MAIN_AREA",
    mower_activity: str = MowerActivity.MOWING,
    mower_state: str = MowerState.IN_OPERATION,
    error_code: int = 0,
    connected: bool = True,
    cutting_height: int = 5,
    headlight_mode: str = HeadlightMode.ALWAYS_OFF,
    has_headlights: bool = True,
    has_work_areas: bool = False,
    has_stay_out_zones: bool = False,
    has_position: bool = True,
    positions: list[Position] | None = None,
    work_areas: dict[int, WorkArea] | None = None,
    stay_out_zones: dict[str, StayOutZone] | None = None,
    tasks: list[ScheduleTask] | None = None,
    next_start_timestamp: datetime | None = None,
    restricted_reason: str = "NONE",
    override_action: str = "NOT_ACTIVE",
    total_cutting_time: int = 36000,
    number_of_collisions: int = 150,
    number_of_charging_cycles: int = 200,
    total_drive_distance: int = 50000,
    cutting_blade_usage_time: int = 18000,
    total_running_time: int = 72000,
    total_searching_time: int = 7200,
) -> AutomowerDevice:
    """Build a real AutomowerDevice dataclass instance for testing."""
    if positions is None:
        positions = [Position(latitude=52.5200, longitude=13.4050)]
    if work_areas is None:
        work_areas = {}
    if stay_out_zones is None:
        stay_out_zones = {}
    if tasks is None:
        tasks = []

    return AutomowerDevice(
        mower_id=mower_id,
        system=SystemInfo(name=name, model=model, serial_number=serial_number),
        battery=BatteryInfo(level=battery_level),
        mower=MowerInfo(
            mode=mower_mode,
            activity=mower_activity,
            state=mower_state,
            error_code=error_code,
            error_code_timestamp=None,
            inactive_reason=None,
            is_error_confirmable=False,
        ),
        calendar=CalendarInfo(tasks=tasks),
        planner=PlannerInfo(
            next_start_timestamp=next_start_timestamp,
            override=PlannerOverride(action=override_action),
            restricted_reason=restricted_reason,
        ),
        metadata=MetadataInfo(
            connected=connected,
            status_timestamp=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        ),
        positions=positions,
        statistics=StatisticsInfo(
            cutting_blade_usage_time=cutting_blade_usage_time,
            number_of_charging_cycles=number_of_charging_cycles,
            number_of_collisions=number_of_collisions,
            total_charging_time=10000,
            total_cutting_time=total_cutting_time,
            total_drive_distance=total_drive_distance,
            total_running_time=total_running_time,
            total_searching_time=total_searching_time,
        ),
        settings=SettingsInfo(
            cutting_height=cutting_height,
            headlight_mode=headlight_mode,
        ),
        capabilities=CapabilitiesInfo(
            headlights=has_headlights,
            work_areas=has_work_areas,
            stay_out_zones=has_stay_out_zones,
            position=has_position,
            can_confirm_error=False,
        ),
        work_areas=work_areas,
        stay_out_zones=stay_out_zones,
    )


@asynccontextmanager
async def _setup_automower(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    devices: dict[str, AutomowerDevice],
) -> AsyncGenerator[AsyncMock, None]:
    """Set up the integration with Automower devices and yield the mock client."""
    with (
        patch(_PATCH_AM_CLIENT) as mock_client_cls,
        patch(_PATCH_AM_AUTH),
        patch(_PATCH_AM_WS) as mock_ws_cls,
    ):
        mock_client = AsyncMock()
        mock_client.async_get_mowers = AsyncMock(return_value=devices)
        mock_client.async_start = AsyncMock()
        mock_client.async_pause = AsyncMock()
        mock_client.async_park_until_next_schedule = AsyncMock()
        mock_client.async_park_until_further_notice = AsyncMock()
        mock_client.async_resume_schedule = AsyncMock()
        mock_client.async_set_headlight_mode = AsyncMock()
        mock_client.async_set_stay_out_zone = AsyncMock()
        mock_client.async_set_cutting_height = AsyncMock()
        mock_client.async_set_work_area_cutting_height = AsyncMock()
        mock_client_cls.return_value = mock_client

        mock_ws = AsyncMock()
        mock_ws.async_connect = AsyncMock()
        mock_ws.async_disconnect = AsyncMock()
        mock_ws_cls.return_value = mock_ws

        config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        yield mock_client


def _find_entity_id(hass: HomeAssistant, domain: str, unique_id_substr: str) -> str:
    """Find an entity ID by domain and unique_id substring."""
    entity_reg = er.async_get(hass)
    for entry in entity_reg.entities.values():
        if (
            entry.domain == domain
            and entry.platform == DOMAIN
            and unique_id_substr in (entry.unique_id or "")
        ):
            return entry.entity_id
    raise AssertionError(
        f"No {domain} entity found with unique_id containing '{unique_id_substr}'"
    )


@pytest.fixture
def automower_config_entry() -> MockConfigEntry:
    """Return a MockConfigEntry for the Automower integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        data=AUTOMOWER_ENTRY_DATA,
        title="Automower",
        version=2,
    )


# ──────────────────────────────────────────────────────────────────────
# 1. Platform Routing
# ──────────────────────────────────────────────────────────────────────


class TestPlatformRouting:
    """Test that platforms correctly delegate based on api_type."""

    async def test_sensor_platform_delegates_to_automower(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("sensor.test_mower_battery")
            assert state is not None
            assert state.state == "75"

    async def test_binary_sensor_platform_delegates_to_automower(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            # device_class=PROBLEM generates entity_id suffix "_problem"
            state = hass.states.get("binary_sensor.test_mower_error")
            assert state is not None

    async def test_lawn_mower_platform_delegates_to_automower(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None

    async def test_automower_only_platforms_noop_for_gardena(
        self, hass: HomeAssistant
    ) -> None:
        """device_tracker, number, calendar do nothing for gardena entries."""
        from .conftest import ENTRY_DATA, make_mock_device

        gardena_entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            title="My Garden",
        )

        device = make_mock_device()
        devices_gardena = {device.device_id: device}

        _PATCH_CLIENT = (
            "custom_components.gardena_smart_system.coordinator.GardenaClient"
        )
        _PATCH_AUTH = (
            "custom_components.gardena_smart_system.coordinator.GardenaAuth"
        )
        _PATCH_WS = (
            "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"
        )

        with (
            patch(_PATCH_CLIENT) as mock_client_cls,
            patch(_PATCH_AUTH),
            patch(_PATCH_WS) as mock_ws_cls,
        ):
            mock_client = AsyncMock()
            mock_client.async_get_devices = AsyncMock(return_value=devices_gardena)
            mock_client.async_get_websocket_url = AsyncMock(return_value="wss://test")
            mock_client_cls.return_value = mock_client
            mock_ws_cls.return_value = AsyncMock()

            gardena_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(gardena_entry.entry_id)
            await hass.async_block_till_done()

        entity_reg = er.async_get(hass)
        for check_domain in ("device_tracker", "number", "calendar"):
            entities = [
                e
                for e in entity_reg.entities.values()
                if e.domain == check_domain and e.platform == DOMAIN
            ]
            assert len(entities) == 0, f"Expected no {check_domain} entities for Gardena"


# ──────────────────────────────────────────────────────────────────────
# 2. Automower Sensor Platform
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerSensor:
    """Test Automower sensor entities."""

    async def test_battery_level_sensor(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(battery_level=75)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("sensor.test_mower_battery")
            assert state is not None
            assert state.state == "75"

    async def test_cutting_height_sensor(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(cutting_height=7)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            # No device_class, so HA uses the translation_key name or falls back
            # Find by unique_id
            entity_id = _find_entity_id(hass, "sensor", "cutting_height")
            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "7"

    async def test_total_cutting_time_sensor_converts_to_hours(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        # 36000 seconds // 3600 = 10 hours
        device = make_mock_automower_device(total_cutting_time=36000)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "sensor", "total_cutting_time")
            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "10"

    async def test_total_collisions_sensor(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(number_of_collisions=150)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "sensor", "total_collisions")
            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "150"

    async def test_next_start_timestamp_sensor(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        next_start = datetime(2025, 6, 16, 8, 0, 0, tzinfo=timezone.utc)
        device = make_mock_automower_device(next_start_timestamp=next_start)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            # device_class=TIMESTAMP -> entity_id suffix "_timestamp"
            state = hass.states.get("sensor.test_mower_next_start")
            assert state is not None
            assert state.state != "unknown"

    async def test_sensor_unique_id(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_reg = er.async_get(hass)
            entry = entity_reg.async_get("sensor.test_mower_battery")
            assert entry is not None
            assert entry.unique_id == "AM-SN-001_battery_level"


# ──────────────────────────────────────────────────────────────────────
# 3. Automower Binary Sensor Platform
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerBinarySensor:
    """Test Automower binary sensor entities."""

    async def test_error_binary_sensor_on_when_error_state(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(mower_state=MowerState.ERROR)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("binary_sensor.test_mower_error")
            assert state is not None
            assert state.state == "on"

    async def test_error_binary_sensor_on_when_fatal_error_state(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(mower_state=MowerState.FATAL_ERROR)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("binary_sensor.test_mower_error")
            assert state is not None
            assert state.state == "on"

    async def test_error_binary_sensor_off_when_normal_state(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(mower_state=MowerState.IN_OPERATION)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("binary_sensor.test_mower_error")
            assert state is not None
            assert state.state == "off"

    async def test_connected_binary_sensor_on_when_connected(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(connected=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("binary_sensor.test_mower_connected")
            assert state is not None
            assert state.state == "on"

    async def test_connected_binary_sensor_unavailable_when_disconnected(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(connected=False)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            # When disconnected, AutomowerEntity.available returns False,
            # so the entity becomes STATE_UNAVAILABLE.
            state = hass.states.get("binary_sensor.test_mower_connected")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE


# ──────────────────────────────────────────────────────────────────────
# 4. Automower Lawn Mower Platform
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerLawnMower:
    """Test Automower lawn mower entities."""

    async def test_activity_mowing_maps_to_mowing(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            mower_activity=MowerActivity.MOWING,
            mower_state=MowerState.IN_OPERATION,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.state == "mowing"

    async def test_activity_charging_maps_to_docked(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            mower_activity=MowerActivity.CHARGING,
            mower_state=MowerState.IN_OPERATION,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.state == "docked"

    async def test_state_paused_maps_to_paused(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            mower_activity=MowerActivity.MOWING,
            mower_state=MowerState.PAUSED,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.state == "paused"

    async def test_state_error_maps_to_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            mower_activity=MowerActivity.MOWING,
            mower_state=MowerState.ERROR,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.state == "error"

    async def test_activity_leaving_maps_to_mowing(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            mower_activity=MowerActivity.LEAVING,
            mower_state=MowerState.IN_OPERATION,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.state == "mowing"

    async def test_activity_parked_in_cs_maps_to_docked(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            mower_activity=MowerActivity.PARKED_IN_CS,
            mower_state=MowerState.IN_OPERATION,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.state == "docked"

    async def test_activity_stopped_in_garden_maps_to_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            mower_activity=MowerActivity.STOPPED_IN_GARDEN,
            mower_state=MowerState.IN_OPERATION,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.state == "error"

    async def test_extra_state_attributes_include_activity_state_mode(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            mower_activity=MowerActivity.MOWING,
            mower_state=MowerState.IN_OPERATION,
            mower_mode="MAIN_AREA",
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert "activity" in state.attributes
            assert "state" in state.attributes
            assert "mode" in state.attributes
            assert state.attributes["activity"] == MowerActivity.MOWING
            assert state.attributes["state"] == MowerState.IN_OPERATION

    async def test_extra_state_attributes_include_error_code_when_nonzero(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            mower_state=MowerState.ERROR,
            error_code=18,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.attributes["error_code"] == 18

    async def test_extra_state_attributes_no_error_code_when_zero(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(error_code=0)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert "error_code" not in state.attributes


class TestAutomowerLawnMowerCommands:
    """Test Automower lawn mower commands."""

    async def test_start_mowing_calls_client(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            await hass.services.async_call(
                "lawn_mower",
                "start_mowing",
                {"entity_id": "lawn_mower.test_mower_mower"},
                blocking=True,
            )

            mock_client.async_start.assert_called_once_with(device.mower_id)

    async def test_dock_calls_client(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            await hass.services.async_call(
                "lawn_mower",
                "dock",
                {"entity_id": "lawn_mower.test_mower_mower"},
                blocking=True,
            )

            mock_client.async_park_until_next_schedule.assert_called_once_with(
                device.mower_id
            )

    async def test_pause_calls_client(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            await hass.services.async_call(
                "lawn_mower",
                "pause",
                {"entity_id": "lawn_mower.test_mower_mower"},
                blocking=True,
            )

            mock_client.async_pause.assert_called_once_with(device.mower_id)

    async def test_auth_error_raises_exception(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            mock_client.async_start.side_effect = AutomowerAuthenticationError(
                "token expired"
            )

            with pytest.raises(Exception):
                await hass.services.async_call(
                    "lawn_mower",
                    "start_mowing",
                    {"entity_id": "lawn_mower.test_mower_mower"},
                    blocking=True,
                )

    async def test_api_error_raises_ha_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            mock_client.async_start.side_effect = AutomowerException("API error")

            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "lawn_mower",
                    "start_mowing",
                    {"entity_id": "lawn_mower.test_mower_mower"},
                    blocking=True,
                )


class TestAutomowerLawnMowerUnavailability:
    """Test lawn mower unavailability."""

    async def test_mower_unavailable_when_disconnected(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(connected=False)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_mower_unavailable_when_removed_from_coordinator(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.state != STATE_UNAVAILABLE

            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_logs_device_offline_and_online_transitions(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry,
        caplog: object,
    ) -> None:
        """Test that Automower device availability transitions are logged."""
        import logging

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            # Device starts online
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state.state != STATE_UNAVAILABLE

            # Go offline — replace with a disconnected device
            offline_device = make_mock_automower_device(connected=False)
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data(
                {offline_device.mower_id: offline_device}
            )
            await hass.async_block_till_done()

            assert any(
                "Device Test Mower is offline" in r.message
                and r.levelno == logging.WARNING
                for r in caplog.records
            )

            # Come back online — replace with a connected device
            caplog.clear()
            online_device = make_mock_automower_device(connected=True)
            coordinator.async_set_updated_data(
                {online_device.mower_id: online_device}
            )
            await hass.async_block_till_done()

            assert any(
                "Device Test Mower is back online" in r.message
                and r.levelno == logging.INFO
                for r in caplog.records
            )


# ──────────────────────────────────────────────────────────────────────
# 5. Automower Switch Platform
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerHeadlightSwitch:
    """Test Automower headlight switch."""

    async def test_headlight_switch_is_on_when_not_always_off(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            headlight_mode=HeadlightMode.ALWAYS_ON, has_headlights=True
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "switch", "headlight")
            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "on"

    async def test_headlight_switch_is_off_when_always_off(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            headlight_mode=HeadlightMode.ALWAYS_OFF, has_headlights=True
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "switch", "headlight")
            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "off"

    async def test_headlight_turn_on_calls_set_headlight_mode(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            headlight_mode=HeadlightMode.ALWAYS_OFF, has_headlights=True
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            entity_id = _find_entity_id(hass, "switch", "headlight")
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": entity_id},
                blocking=True,
            )

            mock_client.async_set_headlight_mode.assert_called_once_with(
                device.mower_id, HeadlightMode.ALWAYS_ON
            )

    async def test_headlight_turn_off_calls_set_headlight_mode(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            headlight_mode=HeadlightMode.ALWAYS_ON, has_headlights=True
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            entity_id = _find_entity_id(hass, "switch", "headlight")
            await hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": entity_id},
                blocking=True,
            )

            mock_client.async_set_headlight_mode.assert_called_once_with(
                device.mower_id, HeadlightMode.ALWAYS_OFF
            )

    async def test_no_headlight_switch_without_capability(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(has_headlights=False)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_reg = er.async_get(hass)
            headlight_entities = [
                e
                for e in entity_reg.entities.values()
                if e.platform == DOMAIN
                and e.domain == "switch"
                and "headlight" in (e.unique_id or "")
            ]
            assert len(headlight_entities) == 0


class TestAutomowerStayOutZoneSwitch:
    """Test Automower stay-out zone switch."""

    async def test_stay_out_zone_switch_reflects_enabled(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        zone = StayOutZone(zone_id="zone-1", name="Garden Pond", enabled=True)
        device = make_mock_automower_device(
            has_stay_out_zones=True,
            stay_out_zones={"zone-1": zone},
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "switch", "soz_zone-1")
            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "on"

    async def test_stay_out_zone_switch_disabled_zone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        zone = StayOutZone(zone_id="zone-2", name="Flower Bed", enabled=False)
        device = make_mock_automower_device(
            has_stay_out_zones=True,
            stay_out_zones={"zone-2": zone},
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "switch", "soz_zone-2")
            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "off"

    async def test_stay_out_zone_toggle_calls_client(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        zone = StayOutZone(zone_id="zone-1", name="Garden Pond", enabled=False)
        device = make_mock_automower_device(
            has_stay_out_zones=True,
            stay_out_zones={"zone-1": zone},
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            entity_id = _find_entity_id(hass, "switch", "soz_zone-1")
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": entity_id},
                blocking=True,
            )

            mock_client.async_set_stay_out_zone.assert_called_once_with(
                device.mower_id, "zone-1", True
            )


# ──────────────────────────────────────────────────────────────────────
# 6. Automower Number Platform
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerNumber:
    """Test Automower number entities."""

    async def test_cutting_height_number_shows_value(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(cutting_height=7)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "number", "cutting_height")
            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "7.0"

    async def test_setting_cutting_height_calls_client(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(cutting_height=5)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            entity_id = _find_entity_id(hass, "number", "cutting_height")
            await hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": entity_id, "value": 8},
                blocking=True,
            )

            mock_client.async_set_cutting_height.assert_called_once_with(
                device.mower_id, 8
            )

    async def test_work_area_cutting_height_shows_value(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        wa = WorkArea(work_area_id=1, name="Front Yard", cutting_height=60, enabled=True)
        device = make_mock_automower_device(
            has_work_areas=True,
            work_areas={1: wa},
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "number", "wa_1_height")
            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "60.0"

    async def test_setting_work_area_height_calls_client(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        wa = WorkArea(work_area_id=1, name="Front Yard", cutting_height=60, enabled=True)
        device = make_mock_automower_device(
            has_work_areas=True,
            work_areas={1: wa},
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            entity_id = _find_entity_id(hass, "number", "wa_1_height")
            await hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": entity_id, "value": 80},
                blocking=True,
            )

            mock_client.async_set_work_area_cutting_height.assert_called_once_with(
                device.mower_id, 1, 80
            )


# ──────────────────────────────────────────────────────────────────────
# 7. Automower Device Tracker
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerDeviceTracker:
    """Test Automower device tracker entities."""

    async def test_tracker_shows_latitude_longitude(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            has_position=True,
            positions=[Position(latitude=52.5200, longitude=13.4050)],
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("device_tracker.test_mower_position")
            assert state is not None
            assert state.attributes["latitude"] == 52.5200
            assert state.attributes["longitude"] == 13.4050

    async def test_no_tracker_when_position_capability_false(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(has_position=False)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_reg = er.async_get(hass)
            tracker_entities = [
                e
                for e in entity_reg.entities.values()
                if e.domain == "device_tracker" and e.platform == DOMAIN
            ]
            assert len(tracker_entities) == 0

    async def test_tracker_returns_none_when_no_positions(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            has_position=True,
            positions=[],
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("device_tracker.test_mower_position")
            assert state is not None
            # latitude/longitude are None when no positions
            assert state.attributes.get("latitude") is None
            assert state.attributes.get("longitude") is None


# ──────────────────────────────────────────────────────────────────────
# 8. Automower Calendar
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerCalendar:
    """Test Automower calendar entities."""

    async def test_calendar_entity_created(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_reg = er.async_get(hass)
            cal_entries = [
                e
                for e in entity_reg.entities.values()
                if e.domain == "calendar" and e.platform == DOMAIN
            ]
            assert len(cal_entries) == 1

    async def test_async_get_events_generates_events_from_tasks(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        task = ScheduleTask(
            start=480,  # 8:00 AM in minutes
            duration=120,  # 2 hours
            monday=True,
            tuesday=False,
            wednesday=True,
            thursday=False,
            friday=True,
            saturday=False,
            sunday=False,
            work_area_id=None,
        )
        device = make_mock_automower_device(tasks=[task])
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            from homeassistant.util import dt as dt_util

            # Test _generate_events directly via the entity
            calendar_entity_id = _find_entity_id(hass, "calendar", "schedule")
            entity_reg = er.async_get(hass)
            entry = entity_reg.async_get(calendar_entity_id)
            assert entry is not None

            # Use the automower_calendar module directly to test _generate_events
            from custom_components.gardena_smart_system.automower_calendar import (
                AutomowerCalendarEntity,
            )

            start = datetime(2025, 6, 16, 0, 0, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
            end = datetime(2025, 6, 22, 23, 59, 59, tzinfo=dt_util.DEFAULT_TIME_ZONE)
            events = AutomowerCalendarEntity._generate_events(device, start, end)
            # Monday=16, Wednesday=18, Friday=20 = 3 events
            assert len(events) == 3
            assert "Mowing" in events[0].summary

    async def test_no_events_when_tasks_empty(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(tasks=[])
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            from custom_components.gardena_smart_system.automower_calendar import (
                AutomowerCalendarEntity,
            )
            from homeassistant.util import dt as dt_util

            start = datetime(2025, 6, 16, 0, 0, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
            end = datetime(2025, 6, 22, 23, 59, 59, tzinfo=dt_util.DEFAULT_TIME_ZONE)
            events = AutomowerCalendarEntity._generate_events(device, start, end)
            assert len(events) == 0


# ──────────────────────────────────────────────────────────────────────
# 9. Automower Coordinator
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerCoordinator:
    """Test the AutomowerCoordinator behavior."""

    async def test_rate_limit_backoff_sets_cooldown_interval(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        from custom_components.gardena_smart_system.const import (
            AUTOMOWER_RATE_LIMIT_COOLDOWN,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        with (
            patch(_PATCH_AM_CLIENT) as mock_client_cls,
            patch(_PATCH_AM_AUTH),
            patch(_PATCH_AM_WS) as mock_ws_cls,
        ):
            mock_client = AsyncMock()
            # First call succeeds (initial setup), second raises rate limit
            mock_client.async_get_mowers = AsyncMock(
                side_effect=[devices, AutomowerRateLimitError("rate limited")]
            )
            mock_client_cls.return_value = mock_client
            mock_ws_cls.return_value = AsyncMock()

            automower_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = automower_config_entry.runtime_data

            # Trigger an update that will get rate limited
            await coordinator.async_refresh()
            await hass.async_block_till_done()

            assert coordinator.update_interval == AUTOMOWER_RATE_LIMIT_COOLDOWN

    async def test_successful_fetch_restores_ws_interval(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        from custom_components.gardena_smart_system.const import (
            AUTOMOWER_SCAN_INTERVAL_WS_CONNECTED,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            # After setup, WS should have been started and interval set
            # to the WS-connected interval
            assert coordinator.update_interval == AUTOMOWER_SCAN_INTERVAL_WS_CONNECTED

    async def test_command_throttle_raises_when_too_fast(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            # First call should succeed
            coordinator.check_command_throttle()

            # Second call immediately should raise
            with pytest.raises(HomeAssistantError):
                coordinator.check_command_throttle()

    async def test_command_throttle_allows_after_interval(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        from custom_components.gardena_smart_system.const import (
            MIN_COMMAND_INTERVAL_SECONDS,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            coordinator.check_command_throttle()

            # Simulate enough time passing by resetting the internal timer
            coordinator._last_command_time = (
                time.monotonic() - MIN_COMMAND_INTERVAL_SECONDS - 1
            )

            # Should not raise
            coordinator.check_command_throttle()


# ──────────────────────────────────────────────────────────────────────
# 10. Device Info and Unique IDs
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerDeviceInfo:
    """Test device info registration for Automower entities."""

    async def test_lawn_mower_unique_id(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_reg = er.async_get(hass)
            entry = entity_reg.async_get("lawn_mower.test_mower_mower")
            assert entry is not None
            assert entry.unique_id == "AM-SN-001_automower"

    async def test_headlight_switch_unique_id(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(has_headlights=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_reg = er.async_get(hass)
            headlight_entry = None
            for entry in entity_reg.entities.values():
                if entry.platform == DOMAIN and "headlight" in (entry.unique_id or ""):
                    headlight_entry = entry
                    break
            assert headlight_entry is not None
            assert headlight_entry.unique_id == "AM-SN-001_headlight"

    async def test_cutting_height_number_unique_id(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_reg = er.async_get(hass)
            num_entry = None
            for entry in entity_reg.entities.values():
                if (
                    entry.platform == DOMAIN
                    and entry.domain == "number"
                    and "cutting_height" in (entry.unique_id or "")
                ):
                    num_entry = entry
                    break
            assert num_entry is not None
            assert num_entry.unique_id == "AM-SN-001_cutting_height"

    async def test_device_tracker_unique_id(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(has_position=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_reg = er.async_get(hass)
            tracker_entry = None
            for entry in entity_reg.entities.values():
                if entry.domain == "device_tracker" and entry.platform == DOMAIN:
                    tracker_entry = entry
                    break
            assert tracker_entry is not None
            assert tracker_entry.unique_id == "AM-SN-001_position"

    async def test_entities_linked_to_same_device(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(has_headlights=True, has_position=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_reg = er.async_get(hass)
            mower_entry = entity_reg.async_get("lawn_mower.test_mower_mower")
            sensor_entry = entity_reg.async_get("sensor.test_mower_battery")

            assert mower_entry is not None
            assert sensor_entry is not None

            # All entities share the same device
            assert mower_entry.device_id == sensor_entry.device_id
            assert mower_entry.device_id is not None


# ──────────────────────────────────────────────────────────────────────
# 11. Coordinator Error Handling & WS Lifecycle
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerCoordinatorErrors:
    """Test coordinator error handling paths."""

    async def test_auth_error_raises_config_entry_auth_failed(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 85: AuthenticationError -> ConfigEntryAuthFailed."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        with (
            patch(_PATCH_AM_CLIENT) as mock_client_cls,
            patch(_PATCH_AM_AUTH),
            patch(_PATCH_AM_WS) as mock_ws_cls,
        ):
            mock_client = AsyncMock()
            mock_client.async_get_mowers = AsyncMock(
                side_effect=[devices, AutomowerAuthenticationError("expired")]
            )
            mock_client_cls.return_value = mock_client
            mock_ws_cls.return_value = AsyncMock()

            automower_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = automower_config_entry.runtime_data
            await coordinator.async_refresh()
            await hass.async_block_till_done()

            # ConfigEntryAuthFailed sets the entry to SETUP_ERROR
            assert coordinator.last_update_success is False

    async def test_connection_error_raises_update_failed(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 97: ConnectionError -> UpdateFailed."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        with (
            patch(_PATCH_AM_CLIENT) as mock_client_cls,
            patch(_PATCH_AM_AUTH),
            patch(_PATCH_AM_WS) as mock_ws_cls,
        ):
            mock_client = AsyncMock()
            mock_client.async_get_mowers = AsyncMock(
                side_effect=[devices, AutomowerConnectionError("offline")]
            )
            mock_client_cls.return_value = mock_client
            mock_ws_cls.return_value = AsyncMock()

            automower_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = automower_config_entry.runtime_data
            await coordinator.async_refresh()
            await hass.async_block_till_done()

            assert coordinator.last_update_success is False

    async def test_restore_normal_interval_after_rate_limit(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 106-110: Restore normal interval after successful fetch."""
        from custom_components.gardena_smart_system.const import (
            AUTOMOWER_RATE_LIMIT_COOLDOWN,
            AUTOMOWER_SCAN_INTERVAL_WS_CONNECTED,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        with (
            patch(_PATCH_AM_CLIENT) as mock_client_cls,
            patch(_PATCH_AM_AUTH),
            patch(_PATCH_AM_WS) as mock_ws_cls,
        ):
            mock_client = AsyncMock()
            # First: success (setup), second: rate limit, third: success (restore)
            mock_client.async_get_mowers = AsyncMock(
                side_effect=[
                    devices,
                    AutomowerRateLimitError("rate limited"),
                    devices,
                ]
            )
            mock_client_cls.return_value = mock_client
            mock_ws_cls.return_value = AsyncMock()

            automower_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = automower_config_entry.runtime_data

            # Trigger rate limit
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            assert coordinator.update_interval == AUTOMOWER_RATE_LIMIT_COOLDOWN

            # Trigger successful fetch that restores interval
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            assert coordinator.update_interval == AUTOMOWER_SCAN_INTERVAL_WS_CONNECTED


class TestAutomowerCoordinatorStaleDevices:
    """Test stale device removal."""

    async def test_stale_device_removed_from_registry(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 128-146: Remove devices no longer in API response."""
        device1 = make_mock_automower_device(
            mower_id="mower-1", serial_number="SN-001", name="Mower One"
        )
        device2 = make_mock_automower_device(
            mower_id="mower-2", serial_number="SN-002", name="Mower Two"
        )
        both_devices = {device1.mower_id: device1, device2.mower_id: device2}
        one_device = {device1.mower_id: device1}

        with (
            patch(_PATCH_AM_CLIENT) as mock_client_cls,
            patch(_PATCH_AM_AUTH),
            patch(_PATCH_AM_WS) as mock_ws_cls,
        ):
            mock_client = AsyncMock()
            # First call returns both, second returns only device1
            mock_client.async_get_mowers = AsyncMock(
                side_effect=[both_devices, one_device]
            )
            mock_client_cls.return_value = mock_client
            mock_ws_cls.return_value = AsyncMock()

            automower_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            device_reg = dr.async_get(hass)
            # Both devices should exist
            assert device_reg.async_get_device(identifiers={(DOMAIN, "SN-001")})
            assert device_reg.async_get_device(identifiers={(DOMAIN, "SN-002")})

            coordinator = automower_config_entry.runtime_data
            await coordinator.async_refresh()
            await hass.async_block_till_done()

            # Device 2 should be removed
            assert device_reg.async_get_device(identifiers={(DOMAIN, "SN-001")})
            assert device_reg.async_get_device(identifiers={(DOMAIN, "SN-002")}) is None


class TestAutomowerCoordinatorWebSocket:
    """Test WebSocket lifecycle in the coordinator."""

    async def test_ws_connect_exception_falls_back_to_polling(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 171-176: WS connect exception -> fall back to polling."""
        from custom_components.gardena_smart_system.const import (
            AUTOMOWER_SCAN_INTERVAL,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        with (
            patch(_PATCH_AM_CLIENT) as mock_client_cls,
            patch(_PATCH_AM_AUTH),
            patch(_PATCH_AM_WS) as mock_ws_cls,
        ):
            mock_client = AsyncMock()
            mock_client.async_get_mowers = AsyncMock(return_value=devices)
            mock_client_cls.return_value = mock_client

            mock_ws = AsyncMock()
            mock_ws.async_connect = AsyncMock(
                side_effect=Exception("WS connect failed")
            )
            mock_ws_cls.return_value = mock_ws

            automower_config_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            coordinator = automower_config_entry.runtime_data
            # WS failed, so should stay at normal polling interval
            assert coordinator.update_interval == AUTOMOWER_SCAN_INTERVAL
            assert coordinator._ws_connected is False

    async def test_on_device_update_updates_coordinator_data(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 188-190: WS push update handler."""
        device = make_mock_automower_device(battery_level=75)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            # Simulate a WS push update with updated battery
            updated_device = make_mock_automower_device(battery_level=50)
            coordinator._on_device_update(device.mower_id, updated_device)
            await hass.async_block_till_done()

            assert coordinator.data[device.mower_id].battery.level == 50

    async def test_on_device_update_with_none_data(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 188-190: WS push update when data is None."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.data = None

            updated_device = make_mock_automower_device(battery_level=50)
            coordinator._on_device_update(device.mower_id, updated_device)
            await hass.async_block_till_done()

            # Should set data to empty dict via async_set_updated_data
            assert coordinator.data == {}

    async def test_on_ws_error_creates_repair_issue(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 194-197: WS error handler sets repair issue."""
        from custom_components.gardena_smart_system.const import (
            AUTOMOWER_SCAN_INTERVAL,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            assert coordinator._ws_connected is True

            # Simulate WS error
            coordinator._on_ws_error(Exception("connection lost"))

            assert coordinator._ws_connected is False
            assert coordinator.update_interval == AUTOMOWER_SCAN_INTERVAL

            # Check repair issue was created
            issue_reg = ir.async_get(hass)
            issue = issue_reg.async_get_issue(
                DOMAIN, "automower_websocket_connection_failed"
            )
            assert issue is not None


# ──────────────────────────────────────────────────────────────────────
# 12. Switch Error Handling
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerSwitchErrors:
    """Test switch error handling paths."""

    async def test_headlight_device_unavailable_raises(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 97-101: Device unavailable raises HomeAssistantError."""
        from custom_components.gardena_smart_system.automower_switch import (
            AutomowerHeadlightSwitch,
        )

        device = make_mock_automower_device(has_headlights=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            # Directly instantiate and test the method since HA skips unavailable entities
            entity = AutomowerHeadlightSwitch(coordinator, device)
            entity.hass = hass
            with pytest.raises(HomeAssistantError):
                await entity.async_turn_on()

    async def test_headlight_auth_error_raises_config_entry_auth_failed(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 107-114: AuthenticationError -> ConfigEntryAuthFailed."""
        device = make_mock_automower_device(has_headlights=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            entity_id = _find_entity_id(hass, "switch", "headlight")
            mock_client.async_set_headlight_mode.side_effect = (
                AutomowerAuthenticationError("expired")
            )

            with pytest.raises(Exception):
                await hass.services.async_call(
                    "switch", "turn_on", {"entity_id": entity_id}, blocking=True
                )

    async def test_headlight_generic_error_raises_ha_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 113-118: AutomowerException -> HomeAssistantError."""
        device = make_mock_automower_device(has_headlights=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            entity_id = _find_entity_id(hass, "switch", "headlight")
            mock_client.async_set_headlight_mode.side_effect = AutomowerException(
                "API error"
            )

            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "switch", "turn_on", {"entity_id": entity_id}, blocking=True
                )

    async def test_zone_device_unavailable_raises(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 160-164: Zone device unavailable."""
        from custom_components.gardena_smart_system.automower_switch import (
            AutomowerStayOutZoneSwitch,
        )

        zone = StayOutZone(zone_id="zone-1", name="Pond", enabled=False)
        device = make_mock_automower_device(
            has_stay_out_zones=True, stay_out_zones={"zone-1": zone}
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            entity = AutomowerStayOutZoneSwitch(coordinator, device, "zone-1")
            entity.hass = hass
            with pytest.raises(HomeAssistantError):
                await entity.async_turn_on()

    async def test_zone_auth_error_raises(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 170-175: Zone AuthenticationError -> ConfigEntryAuthFailed."""
        zone = StayOutZone(zone_id="zone-1", name="Pond", enabled=False)
        device = make_mock_automower_device(
            has_stay_out_zones=True, stay_out_zones={"zone-1": zone}
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            entity_id = _find_entity_id(hass, "switch", "soz_zone-1")
            mock_client.async_set_stay_out_zone.side_effect = (
                AutomowerAuthenticationError("expired")
            )

            with pytest.raises(Exception):
                await hass.services.async_call(
                    "switch", "turn_on", {"entity_id": entity_id}, blocking=True
                )

    async def test_zone_generic_error_raises_ha_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 176-181: Zone AutomowerException -> HomeAssistantError."""
        zone = StayOutZone(zone_id="zone-1", name="Pond", enabled=False)
        device = make_mock_automower_device(
            has_stay_out_zones=True, stay_out_zones={"zone-1": zone}
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            entity_id = _find_entity_id(hass, "switch", "soz_zone-1")
            mock_client.async_set_stay_out_zone.side_effect = AutomowerException(
                "API error"
            )

            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "switch", "turn_on", {"entity_id": entity_id}, blocking=True
                )

    async def test_headlight_is_on_returns_none_when_device_unavailable(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 84: is_on returns None when device is None."""
        device = make_mock_automower_device(has_headlights=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "switch", "headlight")

            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_zone_is_on_returns_none_when_device_unavailable(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 144: is_on returns None when device is None."""
        zone = StayOutZone(zone_id="zone-1", name="Pond", enabled=True)
        device = make_mock_automower_device(
            has_stay_out_zones=True, stay_out_zones={"zone-1": zone}
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "switch", "soz_zone-1")

            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == STATE_UNAVAILABLE


# ──────────────────────────────────────────────────────────────────────
# 13. Number Error Handling
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerNumberErrors:
    """Test number entity error handling paths."""

    async def test_cutting_height_device_unavailable_raises(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 88-92: Device unavailable raises HomeAssistantError."""
        from custom_components.gardena_smart_system.automower_number import (
            AutomowerCuttingHeightEntity,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            entity = AutomowerCuttingHeightEntity(coordinator, device)
            entity.hass = hass
            with pytest.raises(HomeAssistantError):
                await entity.async_set_native_value(5)

    async def test_cutting_height_auth_error_raises(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 98-105: AuthenticationError -> ConfigEntryAuthFailed."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            entity_id = _find_entity_id(hass, "number", "cutting_height")
            mock_client.async_set_cutting_height.side_effect = (
                AutomowerAuthenticationError("expired")
            )

            with pytest.raises(Exception):
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": entity_id, "value": 5},
                    blocking=True,
                )

    async def test_cutting_height_generic_error_raises_ha_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 104-109: AutomowerException -> HomeAssistantError."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            entity_id = _find_entity_id(hass, "number", "cutting_height")
            mock_client.async_set_cutting_height.side_effect = AutomowerException(
                "API error"
            )

            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": entity_id, "value": 5},
                    blocking=True,
                )

    async def test_cutting_height_native_value_none_when_unavailable(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 82: native_value returns None when device is None."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "number", "cutting_height")

            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_work_area_height_device_unavailable_raises(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 152-155: Work area device unavailable."""
        from custom_components.gardena_smart_system.automower_number import (
            AutomowerWorkAreaHeightEntity,
        )

        wa = WorkArea(work_area_id=1, name="Front Yard", cutting_height=60, enabled=True)
        device = make_mock_automower_device(has_work_areas=True, work_areas={1: wa})
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            entity = AutomowerWorkAreaHeightEntity(coordinator, device, 1)
            entity.hass = hass
            with pytest.raises(HomeAssistantError):
                await entity.async_set_native_value(50)

    async def test_work_area_height_auth_error_raises(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 161-168: Work area AuthenticationError."""
        wa = WorkArea(work_area_id=1, name="Front Yard", cutting_height=60, enabled=True)
        device = make_mock_automower_device(has_work_areas=True, work_areas={1: wa})
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            entity_id = _find_entity_id(hass, "number", "wa_1_height")
            mock_client.async_set_work_area_cutting_height.side_effect = (
                AutomowerAuthenticationError("expired")
            )

            with pytest.raises(Exception):
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": entity_id, "value": 50},
                    blocking=True,
                )

    async def test_work_area_height_generic_error_raises_ha_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 167-172: Work area AutomowerException."""
        wa = WorkArea(work_area_id=1, name="Front Yard", cutting_height=60, enabled=True)
        device = make_mock_automower_device(has_work_areas=True, work_areas={1: wa})
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            entity_id = _find_entity_id(hass, "number", "wa_1_height")
            mock_client.async_set_work_area_cutting_height.side_effect = (
                AutomowerException("API error")
            )

            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": entity_id, "value": 50},
                    blocking=True,
                )

    async def test_work_area_native_value_none_when_unavailable(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 142: native_value returns None when device is None."""
        wa = WorkArea(work_area_id=1, name="Front Yard", cutting_height=60, enabled=True)
        device = make_mock_automower_device(has_work_areas=True, work_areas={1: wa})
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "number", "wa_1_height")

            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == STATE_UNAVAILABLE


# ──────────────────────────────────────────────────────────────────────
# 14. Lawn Mower Additional Coverage
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerLawnMowerAdditional:
    """Additional lawn mower coverage for missing lines."""

    async def test_activity_none_when_device_unavailable(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 86: activity returns None when device is None."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_extra_state_attributes_none_when_device_unavailable(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 98: extra_state_attributes returns None when device is None."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            # When unavailable, no extra attributes
            assert "activity" not in state.attributes

    async def test_extra_state_attributes_restricted_reason(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 107: restricted_reason included when not NONE."""
        device = make_mock_automower_device(
            restricted_reason="WEEK_SCHEDULE",
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.attributes["restricted_reason"] == "WEEK_SCHEDULE"

    async def test_extra_state_attributes_override_action(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 109: override_action included when not NOT_ACTIVE."""
        device = make_mock_automower_device(
            override_action="FORCE_MOW",
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.attributes["override_action"] == "FORCE_MOW"

    async def test_fatal_error_state_maps_to_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 88: FATAL_ERROR maps to LawnMowerActivity.ERROR."""
        device = make_mock_automower_device(
            mower_activity=MowerActivity.MOWING,
            mower_state=MowerState.FATAL_ERROR,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("lawn_mower.test_mower_mower")
            assert state is not None
            assert state.state == "error"

    async def test_device_unavailable_command_raises(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 128: Device unavailable when sending command."""
        from custom_components.gardena_smart_system.automower_lawn_mower import (
            AutomowerLawnMowerEntity,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            entity = AutomowerLawnMowerEntity(coordinator, device)
            entity.hass = hass
            with pytest.raises(HomeAssistantError):
                await entity.async_start_mowing()

    async def test_command_auth_error_raises_config_entry_auth_failed(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 145-150: _async_send_command auth error path."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            mock_client.async_pause.side_effect = AutomowerAuthenticationError(
                "expired"
            )

            with pytest.raises(Exception):
                await hass.services.async_call(
                    "lawn_mower",
                    "pause",
                    {"entity_id": "lawn_mower.test_mower_mower"},
                    blocking=True,
                )

    async def test_activity_returns_none_when_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 86: activity returns None when _device is None."""
        from custom_components.gardena_smart_system.automower_lawn_mower import (
            AutomowerLawnMowerEntity,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            entity = AutomowerLawnMowerEntity(coordinator, device)
            entity.hass = hass
            assert entity.activity is None

    async def test_extra_state_attributes_returns_none_when_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 98: extra_state_attributes returns None when _device is None."""
        from custom_components.gardena_smart_system.automower_lawn_mower import (
            AutomowerLawnMowerEntity,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            entity = AutomowerLawnMowerEntity(coordinator, device)
            entity.hass = hass
            assert entity.extra_state_attributes is None

    async def test_send_command_park_until_further_notice(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 141-142: park_until_further_notice command branch."""
        from custom_components.gardena_smart_system.automower_lawn_mower import (
            AutomowerLawnMowerEntity,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            coordinator = automower_config_entry.runtime_data
            entity = AutomowerLawnMowerEntity(coordinator, device)
            entity.hass = hass
            await entity._async_send_command("park_until_further_notice")
            mock_client.async_park_until_further_notice.assert_called_once_with(
                device.mower_id
            )

    async def test_send_command_resume_schedule(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 143-144: resume_schedule command branch."""
        from custom_components.gardena_smart_system.automower_lawn_mower import (
            AutomowerLawnMowerEntity,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            coordinator = automower_config_entry.runtime_data
            entity = AutomowerLawnMowerEntity(coordinator, device)
            entity.hass = hass
            await entity._async_send_command("resume_schedule")
            mock_client.async_resume_schedule.assert_called_once_with(
                device.mower_id
            )


# ──────────────────────────────────────────────────────────────────────
# 15. Calendar Additional Coverage
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerCalendarAdditional:
    """Additional calendar coverage for missing lines."""

    async def test_async_get_events_returns_empty_when_device_none(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 92-95: async_get_events returns [] when device is None."""
        from custom_components.gardena_smart_system.automower_calendar import (
            AutomowerCalendarEntity,
        )
        from homeassistant.util import dt as dt_util

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            # Directly call async_get_events on the entity instance
            entity = AutomowerCalendarEntity(coordinator, device)
            entity.hass = hass
            now = dt_util.now()
            events = await entity.async_get_events(hass, now, now + timedelta(days=7))
            assert events == []

    async def test_event_summary_includes_work_area_name(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 121, 125-126: Work area name in event summary."""
        from custom_components.gardena_smart_system.automower_calendar import (
            AutomowerCalendarEntity,
        )
        from homeassistant.util import dt as dt_util

        wa = WorkArea(work_area_id=1, name="Front Yard", cutting_height=60, enabled=True)
        # Monday task with work_area_id
        task = ScheduleTask(
            start=480,
            duration=120,
            monday=True,
            tuesday=False,
            wednesday=False,
            thursday=False,
            friday=False,
            saturday=False,
            sunday=False,
            work_area_id=1,
        )
        device = make_mock_automower_device(
            has_work_areas=True,
            work_areas={1: wa},
            tasks=[task],
        )

        # Monday June 16, 2025
        start = datetime(2025, 6, 16, 0, 0, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
        end = datetime(2025, 6, 16, 23, 59, 59, tzinfo=dt_util.DEFAULT_TIME_ZONE)
        events = AutomowerCalendarEntity._generate_events(device, start, end)
        assert len(events) == 1
        assert events[0].summary == "Mowing (Front Yard)"

    async def test_event_summary_without_work_area_name(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 125-126: Work area ID not in work_areas dict."""
        from custom_components.gardena_smart_system.automower_calendar import (
            AutomowerCalendarEntity,
        )
        from homeassistant.util import dt as dt_util

        # Task references work_area_id=99 but device has no such work area
        task = ScheduleTask(
            start=480,
            duration=120,
            monday=True,
            tuesday=False,
            wednesday=False,
            thursday=False,
            friday=False,
            saturday=False,
            sunday=False,
            work_area_id=99,
        )
        device = make_mock_automower_device(tasks=[task])

        start = datetime(2025, 6, 16, 0, 0, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
        end = datetime(2025, 6, 16, 23, 59, 59, tzinfo=dt_util.DEFAULT_TIME_ZONE)
        events = AutomowerCalendarEntity._generate_events(device, start, end)
        assert len(events) == 1
        # No work area match, so summary is just "Mowing" without suffix
        assert events[0].summary == "Mowing"


# ──────────────────────────────────────────────────────────────────────
# 16. Diagnostics
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerDiagnostics:
    """Test diagnostics for Automower entries."""

    async def test_automower_diagnostics(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 32, 74-105: Automower diagnostics serialization."""
        from custom_components.gardena_smart_system.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        wa = WorkArea(work_area_id=1, name="Front Yard", cutting_height=60, enabled=True)
        zone = StayOutZone(zone_id="zone-1", name="Pond", enabled=True)
        device = make_mock_automower_device(
            has_work_areas=True,
            work_areas={1: wa},
            has_stay_out_zones=True,
            stay_out_zones={"zone-1": zone},
            tasks=[
                ScheduleTask(
                    start=480, duration=120,
                    monday=True, tuesday=False, wednesday=False,
                    thursday=False, friday=False, saturday=False, sunday=False,
                    work_area_id=None,
                )
            ],
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            result = await async_get_config_entry_diagnostics(
                hass, automower_config_entry
            )

            assert "config_entry" in result
            assert "devices" in result
            devices_data = result["devices"]
            assert device.mower_id in devices_data

            mower_data = devices_data[device.mower_id]
            assert mower_data["name"] == "Test Mower"
            assert mower_data["model"] == "HUSQVARNA AUTOMOWER 450XH"
            assert "battery" in mower_data
            assert "mower" in mower_data
            assert "planner" in mower_data
            assert "statistics" in mower_data
            assert "settings" in mower_data
            assert "capabilities" in mower_data
            assert mower_data["positions_count"] == 1
            assert "1" in mower_data["work_areas"]
            assert mower_data["work_areas"]["1"]["name"] == "Front Yard"
            assert "zone-1" in mower_data["stay_out_zones"]
            assert mower_data["schedule_tasks_count"] == 1

    async def test_automower_diagnostics_empty_data(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Line 74: Empty data returns empty dict."""
        from custom_components.gardena_smart_system.diagnostics import (
            _serialize_automower_devices,
        )

        assert _serialize_automower_devices(None) == {}
        assert _serialize_automower_devices({}) == {}


# ──────────────────────────────────────────────────────────────────────
# 17. Config Flow Additional Coverage
# ──────────────────────────────────────────────────────────────────────


_PATCH_CF_AUTH = "custom_components.gardena_smart_system.config_flow.GardenaAuth"
_PATCH_CF_CLIENT = "custom_components.gardena_smart_system.config_flow.GardenaClient"
_PATCH_CF_AM_CLIENT = "aioautomower.AutomowerClient"


class TestConfigFlowAdditional:
    """Test config flow paths not covered by test_config_flow.py."""

    async def test_user_step_rate_limit_error(self, hass: HomeAssistant) -> None:
        """Line 83: GardenaRateLimitError in user step."""
        from aiogardenasmart.exceptions import GardenaRateLimitError

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

        mock_auth = AsyncMock()
        mock_auth.async_ensure_valid_token = AsyncMock(
            side_effect=GardenaRateLimitError("too many")
        )
        mock_auth.async_revoke_token = AsyncMock()

        with patch(_PATCH_CF_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "test", "client_secret": "test"},
            )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "rate_limited"

    async def test_api_type_gardena_forbidden_error(self, hass: HomeAssistant) -> None:
        """Line 127: Gardena forbidden error in api_type step."""
        from aiogardenasmart.exceptions import GardenaForbiddenError

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

        mock_auth = AsyncMock()
        mock_auth.async_ensure_valid_token = AsyncMock()
        mock_auth.async_revoke_token = AsyncMock()

        with patch(_PATCH_CF_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "test", "client_secret": "test"},
            )

        mock_client = AsyncMock()
        mock_client.async_get_locations = AsyncMock(
            side_effect=GardenaForbiddenError("forbidden")
        )

        with patch(_PATCH_CF_CLIENT, return_value=mock_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"api_type": "gardena"},
            )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "forbidden"

    async def test_reauth_automower_entry(self, hass: HomeAssistant) -> None:
        """Line 204: Reauth for automower api_type entry."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                "client_id": "old-id",
                "client_secret": "old-secret",
                "api_type": "automower",
            },
            title="Automower",
            version=2,
        )
        entry.add_to_hass(hass)
        result = await entry.start_reauth_flow(hass)

        mock_am_client = AsyncMock()
        mock_am_client.async_get_mowers = AsyncMock(return_value={})

        with patch(_PATCH_CF_AM_CLIENT, return_value=mock_am_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "new-id", "client_secret": "new-secret"},
            )

        assert result["type"] == "abort"
        assert result["reason"] == "reauth_successful"
        assert entry.data["client_id"] == "new-id"

    async def test_reconfigure_automower_entry(self, hass: HomeAssistant) -> None:
        """Line 253: Reconfigure for automower api_type entry."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={
                "client_id": "old-id",
                "client_secret": "old-secret",
                "api_type": "automower",
            },
            title="Automower",
            version=2,
        )
        entry.add_to_hass(hass)
        result = await entry.start_reconfigure_flow(hass)

        mock_am_client = AsyncMock()
        mock_am_client.async_get_mowers = AsyncMock(return_value={})

        with patch(_PATCH_CF_AM_CLIENT, return_value=mock_am_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "new-id", "client_secret": "new-secret"},
            )

        assert result["type"] == "abort"
        assert entry.data["client_id"] == "new-id"

    async def test_automower_test_auth_error(self, hass: HomeAssistant) -> None:
        """Line 371: _async_test_automower auth error path."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

        mock_auth = AsyncMock()
        mock_auth.async_ensure_valid_token = AsyncMock()
        mock_auth.async_revoke_token = AsyncMock()

        with patch(_PATCH_CF_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "test", "client_secret": "test"},
            )

        mock_am_client = AsyncMock()
        mock_am_client.async_get_mowers = AsyncMock(
            side_effect=AutomowerAuthenticationError("bad token")
        )

        with patch(_PATCH_CF_AM_CLIENT, return_value=mock_am_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"api_type": "automower"},
            )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "invalid_auth"

    async def test_automower_test_rate_limit_error(self, hass: HomeAssistant) -> None:
        """Line 374: _async_test_automower rate limit path."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

        mock_auth = AsyncMock()
        mock_auth.async_ensure_valid_token = AsyncMock()
        mock_auth.async_revoke_token = AsyncMock()

        with patch(_PATCH_CF_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "test", "client_secret": "test"},
            )

        mock_am_client = AsyncMock()
        mock_am_client.async_get_mowers = AsyncMock(
            side_effect=AutomowerRateLimitError("too many")
        )

        with patch(_PATCH_CF_AM_CLIENT, return_value=mock_am_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"api_type": "automower"},
            )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "rate_limited"

    async def test_automower_test_connection_error(self, hass: HomeAssistant) -> None:
        """Line 376: _async_test_automower connection error path."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

        mock_auth = AsyncMock()
        mock_auth.async_ensure_valid_token = AsyncMock()
        mock_auth.async_revoke_token = AsyncMock()

        with patch(_PATCH_CF_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "test", "client_secret": "test"},
            )

        mock_am_client = AsyncMock()
        mock_am_client.async_get_mowers = AsyncMock(
            side_effect=AutomowerConnectionError("offline")
        )

        with patch(_PATCH_CF_AM_CLIENT, return_value=mock_am_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"api_type": "automower"},
            )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "cannot_connect"

    async def test_automower_test_unknown_error(self, hass: HomeAssistant) -> None:
        """Lines 378-380: _async_test_automower unknown error path."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

        mock_auth = AsyncMock()
        mock_auth.async_ensure_valid_token = AsyncMock()
        mock_auth.async_revoke_token = AsyncMock()

        with patch(_PATCH_CF_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "test", "client_secret": "test"},
            )

        mock_am_client = AsyncMock()
        mock_am_client.async_get_mowers = AsyncMock(
            side_effect=RuntimeError("unexpected")
        )

        with patch(_PATCH_CF_AM_CLIENT, return_value=mock_am_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"api_type": "automower"},
            )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "unknown"

    async def test_gardena_test_rate_limit_error(self, hass: HomeAssistant) -> None:
        """Line 351: _async_test_gardena rate limit path."""
        from aiogardenasmart.exceptions import GardenaRateLimitError

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

        mock_auth = AsyncMock()
        mock_auth.async_ensure_valid_token = AsyncMock()
        mock_auth.async_revoke_token = AsyncMock()

        with patch(_PATCH_CF_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "test", "client_secret": "test"},
            )

        mock_client = AsyncMock()
        mock_client.async_get_locations = AsyncMock(
            side_effect=GardenaRateLimitError("too many")
        )

        with patch(_PATCH_CF_CLIENT, return_value=mock_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"api_type": "gardena"},
            )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "rate_limited"

    async def test_gardena_test_unknown_error(self, hass: HomeAssistant) -> None:
        """Lines 354-356: _async_test_gardena unknown error path."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

        mock_auth = AsyncMock()
        mock_auth.async_ensure_valid_token = AsyncMock()
        mock_auth.async_revoke_token = AsyncMock()

        with patch(_PATCH_CF_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "test", "client_secret": "test"},
            )

        mock_client = AsyncMock()
        mock_client.async_get_locations = AsyncMock(
            side_effect=RuntimeError("unexpected")
        )

        with patch(_PATCH_CF_CLIENT, return_value=mock_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"api_type": "gardena"},
            )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "unknown"
