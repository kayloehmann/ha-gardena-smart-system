"""Tests for the Automower integration components."""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,  # type: ignore[no-redef]
    )

from aioautomower.const import HeadlightMode, MowerActivity, MowerState
from aioautomower.exceptions import (
    AutomowerAuthenticationError,
    AutomowerConnectionError,
    AutomowerException,
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

_PATCH_AM_CLIENT = "custom_components.gardena_smart_system.automower_coordinator.AutomowerClient"
_PATCH_AM_AUTH = "custom_components.gardena_smart_system.automower_coordinator.GardenaAuth"
_PATCH_AM_WS = "custom_components.gardena_smart_system.automower_coordinator.AutomowerWebSocket"

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
    error_code_timestamp: datetime | None = None,
    inactive_reason: str | None = None,
    is_error_confirmable: bool = False,
    can_confirm_error: bool = False,
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
            error_code_timestamp=error_code_timestamp,
            inactive_reason=inactive_reason,
            is_error_confirmable=is_error_confirmable,
        ),
        calendar=CalendarInfo(tasks=tasks),
        planner=PlannerInfo(
            next_start_timestamp=next_start_timestamp,
            override=PlannerOverride(action=override_action),
            restricted_reason=restricted_reason,
        ),
        metadata=MetadataInfo(
            connected=connected,
            status_timestamp=datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC),
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
            can_confirm_error=can_confirm_error,
        ),
        work_areas=work_areas,
        stay_out_zones=stay_out_zones,
    )


@asynccontextmanager
async def _setup_automower(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    devices: dict[str, AutomowerDevice],
) -> AsyncGenerator[AsyncMock]:
    """Set up the integration with Automower devices and yield the mock client."""
    with (
        patch(_PATCH_AM_CLIENT) as mock_client_cls,
        patch(_PATCH_AM_AUTH, return_value=AsyncMock()),
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
    raise AssertionError(f"No {domain} entity found with unique_id containing '{unique_id_substr}'")


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

    async def test_automower_only_platforms_noop_for_gardena(self, hass: HomeAssistant) -> None:
        """device_tracker, number, calendar do nothing for gardena entries."""
        from .conftest import ENTRY_DATA, make_mock_device

        gardena_entry = MockConfigEntry(
            domain=DOMAIN,
            data=ENTRY_DATA,
            title="My Garden",
        )

        device = make_mock_device()
        devices_gardena = {device.device_id: device}

        _PATCH_CLIENT = "custom_components.gardena_smart_system.coordinator.GardenaClient"
        _PATCH_AUTH = "custom_components.gardena_smart_system.coordinator.GardenaAuth"
        _PATCH_WS = "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"

        with (
            patch(_PATCH_CLIENT) as mock_client_cls,
            patch(_PATCH_AUTH, return_value=AsyncMock()),
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
        next_start = datetime(2025, 6, 16, 8, 0, 0, tzinfo=UTC)
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

    async def test_activity_enum_sensor(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        from aioautomower.const import MowerActivity

        device = make_mock_automower_device(mower_activity=MowerActivity.MOWING)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("sensor.test_mower_activity")
            assert state is not None
            assert state.state == "mowing"
            assert state.attributes.get("device_class") == "enum"

    async def test_state_enum_sensor(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        from aioautomower.const import MowerState

        device = make_mock_automower_device(mower_state=MowerState.IN_OPERATION)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("sensor.test_mower_state")
            assert state is not None
            assert state.state == "in_operation"
            assert state.attributes.get("device_class") == "enum"


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

            mock_client.async_park_until_next_schedule.assert_called_once_with(device.mower_id)

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
            mock_client.async_start.side_effect = AutomowerAuthenticationError("token expired")

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


class TestAutomowerLawnMowerServiceActions:
    """Test custom Automower service actions (park_until_further_notice, resume_schedule)."""

    async def test_park_until_further_notice_service(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            await hass.services.async_call(
                "gardena_smart_system",
                "park_until_further_notice",
                {"entity_id": "lawn_mower.test_mower_mower"},
                blocking=True,
            )

            mock_client.async_park_until_further_notice.assert_called_once_with(device.mower_id)

    async def test_resume_schedule_service(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            await hass.services.async_call(
                "gardena_smart_system",
                "resume_schedule",
                {"entity_id": "lawn_mower.test_mower_mower"},
                blocking=True,
            )

            mock_client.async_resume_schedule.assert_called_once_with(device.mower_id)


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
        self,
        hass: HomeAssistant,
        automower_config_entry: MockConfigEntry,
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
            coordinator.async_set_updated_data({offline_device.mower_id: offline_device})
            await hass.async_block_till_done()

            assert any(
                "Device Test Mower is offline" in r.message and r.levelno == logging.WARNING
                for r in caplog.records
            )

            # Come back online — replace with a connected device
            caplog.clear()
            online_device = make_mock_automower_device(connected=True)
            coordinator.async_set_updated_data({online_device.mower_id: online_device})
            await hass.async_block_till_done()

            assert any(
                "Device Test Mower is back online" in r.message and r.levelno == logging.INFO
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

            mock_client.async_set_cutting_height.assert_called_once_with(device.mower_id, 8)

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
            # Entity is disabled by default (F4 security fix — GPS is sensitive)
            entity_id = "device_tracker.test_mower_position"
            entity_reg = er.async_get(hass)
            entry = entity_reg.async_get(entity_id)
            assert entry is not None
            assert entry.disabled_by is not None

            # Enable it and reload
            entity_reg.async_update_entity(entity_id, disabled_by=None)
            await hass.config_entries.async_reload(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            state = hass.states.get(entity_id)
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
            entity_id = "device_tracker.test_mower_position"
            entity_reg = er.async_get(hass)
            entity_reg.async_update_entity(entity_id, disabled_by=None)
            await hass.config_entries.async_reload(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            state = hass.states.get(entity_id)
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
            from homeassistant.util import dt as dt_util

            from custom_components.gardena_smart_system.automower_calendar import (
                AutomowerCalendarEntity,
            )

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
            patch(_PATCH_AM_AUTH, return_value=AsyncMock()),
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

            # First hit: graduated backoff starts at 5 minutes
            from datetime import timedelta

            assert coordinator.update_interval == timedelta(minutes=5)

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
            coordinator._last_command_time = time.monotonic() - MIN_COMMAND_INTERVAL_SECONDS - 1

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
                if (
                    entry.platform == DOMAIN
                    and entry.domain == "switch"
                    and "headlight" in (entry.unique_id or "")
                ):
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
            patch(_PATCH_AM_AUTH, return_value=AsyncMock()),
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
            patch(_PATCH_AM_AUTH, return_value=AsyncMock()),
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
            patch(_PATCH_AM_AUTH, return_value=AsyncMock()),
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
            # First hit: graduated backoff starts at 5 minutes
            from datetime import timedelta

            assert coordinator.update_interval == timedelta(minutes=5)

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

        def _make_one_device():
            return {device1.mower_id: device1}

        with (
            patch(_PATCH_AM_CLIENT) as mock_client_cls,
            patch(_PATCH_AM_AUTH, return_value=AsyncMock()),
            patch(_PATCH_AM_WS) as mock_ws_cls,
        ):
            mock_client = AsyncMock()
            # First call returns both, subsequent calls return only device1
            # Each call returns a fresh dict to avoid mutation side effects
            mock_client.async_get_mowers = AsyncMock(
                side_effect=[
                    both_devices,
                    _make_one_device(),
                    _make_one_device(),
                    _make_one_device(),
                ]
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

            # Device must be absent for _STALE_THRESHOLD polls before removal
            for i in range(coordinator._STALE_THRESHOLD - 1):
                await coordinator.async_refresh()
                await hass.async_block_till_done()
                # Not removed yet
                assert device_reg.async_get_device(identifiers={(DOMAIN, "SN-002")})

            # Final miss — now it should be removed
            await coordinator.async_refresh()
            await hass.async_block_till_done()
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
            patch(_PATCH_AM_AUTH, return_value=AsyncMock()),
            patch(_PATCH_AM_WS) as mock_ws_cls,
        ):
            mock_client = AsyncMock()
            mock_client.async_get_mowers = AsyncMock(return_value=devices)
            mock_client_cls.return_value = mock_client

            mock_ws = AsyncMock()
            mock_ws.async_connect = AsyncMock(side_effect=Exception("WS connect failed"))
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
            issue = issue_reg.async_get_issue(DOMAIN, "automower_websocket_connection_failed")
            assert issue is not None

    async def test_ws_reconnect_clears_repair_issue(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Successful WS reconnect deletes the repair issue."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            # Create the issue first via WS error
            coordinator._on_ws_error(Exception("connection lost"))
            issue_reg = ir.async_get(hass)
            issue_id = "automower_websocket_connection_failed"
            assert issue_reg.async_get_issue(DOMAIN, issue_id) is not None

            # Reconnect clears the issue (line 214)
            coordinator._ws_connected = False
            await coordinator._async_start_websocket(devices)

            assert issue_reg.async_get_issue(DOMAIN, issue_id) is None

    async def test_ws_auth_error_triggers_reauth(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Auth errors trigger reauth, not repair issues (lines 233-234)."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            with patch.object(coordinator.config_entry, "async_start_reauth") as mock_reauth:
                coordinator._on_ws_error(AutomowerAuthenticationError("token expired"))

            mock_reauth.assert_called_once_with(hass)

            # No repair issue should be created
            issue_reg = ir.async_get(hass)
            am_issue_id = "automower_websocket_connection_failed"
            assert issue_reg.async_get_issue(DOMAIN, am_issue_id) is None

    async def test_custom_poll_interval_restored_after_rate_limit(
        self, hass: HomeAssistant
    ) -> None:
        """Custom poll interval takes precedence over defaults after rate limit (line 115)."""
        from custom_components.gardena_smart_system.const import (
            AUTOMOWER_RATE_LIMIT_COOLDOWN,
            OPT_POLL_INTERVAL_MINUTES,
        )

        # Create entry with custom poll interval in options
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=AUTOMOWER_ENTRY_DATA,
            title="Automower",
            version=2,
            options={OPT_POLL_INTERVAL_MINUTES: 45},
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, entry, devices) as mock_client:
            coordinator = entry.runtime_data

            # Simulate rate limit then recovery
            coordinator.update_interval = AUTOMOWER_RATE_LIMIT_COOLDOWN
            mock_client.async_get_mowers = AsyncMock(return_value=devices)

            await coordinator._async_update_data()

            assert coordinator.update_interval == timedelta(minutes=45)

    async def test_stale_device_reappears_clears_miss_count(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """A device that reappears clears its stale miss count (line 153)."""
        device_a = make_mock_automower_device(mower_id="mower-a", serial_number="SN-A")
        device_b = make_mock_automower_device(mower_id="mower-b", serial_number="SN-B")
        devices = {device_a.mower_id: device_a, device_b.mower_id: device_b}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            # Simulate mower-b absent for 1 poll
            coordinator._stale_miss_counts["mower-b"] = 1

            # mower-b reappears — miss count should be cleared
            fresh = {device_a.mower_id: device_a, device_b.mower_id: device_b}
            coordinator._async_remove_stale_devices(fresh)

            assert "mower-b" not in coordinator._stale_miss_counts

    async def test_stale_device_without_serial_skipped(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Stale devices without serial_number are skipped (lines 176-177)."""
        device = make_mock_automower_device(mower_id="mower-no-serial", serial_number="SN-1")
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            # Fake device with no serial in stale data
            no_serial_device = make_mock_automower_device(
                mower_id="mower-no-serial", serial_number=""
            )
            coordinator.data = {"mower-no-serial": no_serial_device}
            coordinator._stale_miss_counts["mower-no-serial"] = 2  # at threshold

            coordinator._async_remove_stale_devices({})

            # Should be cleaned up without error
            assert "mower-no-serial" not in coordinator._stale_miss_counts


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
            mock_client.async_set_headlight_mode.side_effect = AutomowerAuthenticationError(
                "expired"
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
            mock_client.async_set_headlight_mode.side_effect = AutomowerException("API error")

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
            mock_client.async_set_stay_out_zone.side_effect = AutomowerAuthenticationError(
                "expired"
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
            mock_client.async_set_stay_out_zone.side_effect = AutomowerException("API error")

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
            mock_client.async_set_cutting_height.side_effect = AutomowerAuthenticationError(
                "expired"
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
            mock_client.async_set_cutting_height.side_effect = AutomowerException("API error")

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
            mock_client.async_set_work_area_cutting_height.side_effect = AutomowerException(
                "API error"
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
            mock_client.async_pause.side_effect = AutomowerAuthenticationError("expired")

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


# ──────────────────────────────────────────────────────────────────────
# 15. Calendar Additional Coverage
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerCalendarAdditional:
    """Additional calendar coverage for missing lines."""

    async def test_async_get_events_returns_empty_when_device_none(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Lines 92-95: async_get_events returns [] when device is None."""
        from homeassistant.util import dt as dt_util

        from custom_components.gardena_smart_system.automower_calendar import (
            AutomowerCalendarEntity,
        )

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
        from homeassistant.util import dt as dt_util

        from custom_components.gardena_smart_system.automower_calendar import (
            AutomowerCalendarEntity,
        )

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
        from homeassistant.util import dt as dt_util

        from custom_components.gardena_smart_system.automower_calendar import (
            AutomowerCalendarEntity,
        )

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
                    start=480,
                    duration=120,
                    monday=True,
                    tuesday=False,
                    wednesday=False,
                    thursday=False,
                    friday=False,
                    saturday=False,
                    sunday=False,
                    work_area_id=None,
                )
            ],
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            result = await async_get_config_entry_diagnostics(hass, automower_config_entry)

            assert "config_entry" in result
            assert "devices" in result
            devices_data = result["devices"]
            assert device.mower_id in devices_data

            mower_data = devices_data[device.mower_id]
            assert mower_data["name"] == "**REDACTED**"
            assert mower_data["model"] == "HUSQVARNA AUTOMOWER 450XH"
            assert "battery" in mower_data
            assert "mower" in mower_data
            assert "planner" in mower_data
            assert "statistics" in mower_data
            assert "settings" in mower_data
            assert "capabilities" in mower_data
            assert mower_data["positions_count"] == 1
            assert "1" in mower_data["work_areas"]
            assert mower_data["work_areas"]["1"]["name"] == "**REDACTED**"
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

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

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

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

        mock_auth = AsyncMock()
        mock_auth.async_ensure_valid_token = AsyncMock()
        mock_auth.async_revoke_token = AsyncMock()

        with patch(_PATCH_CF_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "test", "client_secret": "test"},
            )

        mock_client = AsyncMock()
        mock_client.async_get_locations = AsyncMock(side_effect=GardenaForbiddenError("forbidden"))

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
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

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
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

        mock_auth = AsyncMock()
        mock_auth.async_ensure_valid_token = AsyncMock()
        mock_auth.async_revoke_token = AsyncMock()

        with patch(_PATCH_CF_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "test", "client_secret": "test"},
            )

        mock_am_client = AsyncMock()
        mock_am_client.async_get_mowers = AsyncMock(side_effect=AutomowerRateLimitError("too many"))

        with patch(_PATCH_CF_AM_CLIENT, return_value=mock_am_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"api_type": "automower"},
            )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "rate_limited"

    async def test_automower_test_connection_error(self, hass: HomeAssistant) -> None:
        """Line 376: _async_test_automower connection error path."""
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

        mock_auth = AsyncMock()
        mock_auth.async_ensure_valid_token = AsyncMock()
        mock_auth.async_revoke_token = AsyncMock()

        with patch(_PATCH_CF_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "test", "client_secret": "test"},
            )

        mock_am_client = AsyncMock()
        mock_am_client.async_get_mowers = AsyncMock(side_effect=AutomowerConnectionError("offline"))

        with patch(_PATCH_CF_AM_CLIENT, return_value=mock_am_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"api_type": "automower"},
            )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "cannot_connect"

    async def test_automower_test_unknown_error(self, hass: HomeAssistant) -> None:
        """Lines 378-380: _async_test_automower unknown error path."""
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

        mock_auth = AsyncMock()
        mock_auth.async_ensure_valid_token = AsyncMock()
        mock_auth.async_revoke_token = AsyncMock()

        with patch(_PATCH_CF_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "test", "client_secret": "test"},
            )

        mock_am_client = AsyncMock()
        mock_am_client.async_get_mowers = AsyncMock(side_effect=RuntimeError("unexpected"))

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

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

        mock_auth = AsyncMock()
        mock_auth.async_ensure_valid_token = AsyncMock()
        mock_auth.async_revoke_token = AsyncMock()

        with patch(_PATCH_CF_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "test", "client_secret": "test"},
            )

        mock_client = AsyncMock()
        mock_client.async_get_locations = AsyncMock(side_effect=GardenaRateLimitError("too many"))

        with patch(_PATCH_CF_CLIENT, return_value=mock_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"api_type": "gardena"},
            )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "rate_limited"

    async def test_gardena_test_unknown_error(self, hass: HomeAssistant) -> None:
        """Lines 354-356: _async_test_gardena unknown error path."""
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

        mock_auth = AsyncMock()
        mock_auth.async_ensure_valid_token = AsyncMock()
        mock_auth.async_revoke_token = AsyncMock()

        with patch(_PATCH_CF_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"client_id": "test", "client_secret": "test"},
            )

        mock_client = AsyncMock()
        mock_client.async_get_locations = AsyncMock(side_effect=RuntimeError("unexpected"))

        with patch(_PATCH_CF_CLIENT, return_value=mock_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {"api_type": "gardena"},
            )

        assert result["type"] == "form"
        assert result["errors"]["base"] == "unknown"


# ──────────────────────────────────────────────────────────────────────
# 18. Automower Platform Routing Guards (defensive early returns)
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerRoutingGuards:
    """Test that automower_* async_setup_entry returns early for non-automower entries.

    The main platform files already gate delegation, so these guards are defensive.
    We call the automower_* setup functions directly with a Gardena config entry
    to exercise the early-return branch.
    """

    @pytest.mark.parametrize(
        "module_path",
        [
            "custom_components.gardena_smart_system.automower_sensor",
            "custom_components.gardena_smart_system.automower_binary_sensor",
            "custom_components.gardena_smart_system.automower_switch",
            "custom_components.gardena_smart_system.automower_device_tracker",
            "custom_components.gardena_smart_system.automower_number",
            "custom_components.gardena_smart_system.automower_calendar",
            "custom_components.gardena_smart_system.automower_lawn_mower",
            "custom_components.gardena_smart_system.automower_event",
            "custom_components.gardena_smart_system.automower_button",
        ],
    )
    async def test_routing_guard_returns_early_for_gardena_entry(
        self,
        hass: HomeAssistant,
        module_path: str,
    ) -> None:
        """Each automower_* module returns immediately for non-automower entries."""
        import importlib

        from .conftest import ENTRY_DATA, make_mock_device

        module = importlib.import_module(module_path)

        gardena_entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, title="My Garden")

        # Set up a Gardena coordinator so runtime_data exists
        device = make_mock_device()
        devices = {device.device_id: device}

        _P_CLIENT = "custom_components.gardena_smart_system.coordinator.GardenaClient"
        _P_AUTH = "custom_components.gardena_smart_system.coordinator.GardenaAuth"
        _P_WS = "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"

        with patch(_P_CLIENT) as cls, patch(_P_AUTH), patch(_P_WS) as ws_cls:
            client = AsyncMock()
            client.async_get_devices = AsyncMock(return_value=devices)
            client.async_get_websocket_url = AsyncMock(return_value="wss://t")
            cls.return_value = client
            ws_cls.return_value = AsyncMock()

            gardena_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(gardena_entry.entry_id)
            await hass.async_block_till_done()

        add_entities = AsyncMock()
        await module.async_setup_entry(hass, gardena_entry, add_entities)

        # No entities should have been added
        add_entities.assert_not_called()


# ──────────────────────────────────────────────────────────────────────
# 19. Automower Entity None-Guards (direct property access)
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerEntityNoneGuards:
    """Test entity properties return None/empty when device is gone from coordinator."""

    async def test_binary_sensor_is_on_none_when_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """automower_binary_sensor.py:100-101: is_on returns None."""
        from custom_components.gardena_smart_system.automower_binary_sensor import (
            BINARY_SENSOR_DESCRIPTIONS,
            AutomowerBinarySensorEntity,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            entity = AutomowerBinarySensorEntity(coordinator, device, BINARY_SENSOR_DESCRIPTIONS[0])
            assert entity.is_on is None

    async def test_sensor_native_value_none_when_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """automower_sensor.py:238-239: native_value returns None."""
        from custom_components.gardena_smart_system.automower_sensor import (
            SENSOR_DESCRIPTIONS,
            AutomowerSensorEntity,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            entity = AutomowerSensorEntity(coordinator, device, SENSOR_DESCRIPTIONS[0])
            assert entity.native_value is None

    async def test_calendar_event_none_when_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """automower_calendar.py:71-72: event returns None."""
        from custom_components.gardena_smart_system.automower_calendar import (
            AutomowerCalendarEntity,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            entity = AutomowerCalendarEntity(coordinator, device)
            assert entity.event is None

    async def test_device_tracker_latitude_none_when_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """automower_device_tracker.py:64: latitude returns None."""
        from custom_components.gardena_smart_system.automower_device_tracker import (
            AutomowerTrackerEntity,
        )

        device = make_mock_automower_device(has_position=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            entity = AutomowerTrackerEntity(coordinator, device)
            assert entity.latitude is None
            assert entity.longitude is None

    async def test_zone_is_on_none_when_zone_missing(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """automower_switch.py:138-139: zone is_on returns None when zone missing."""
        from custom_components.gardena_smart_system.automower_switch import (
            AutomowerStayOutZoneSwitch,
        )

        zone = StayOutZone(zone_id="zone-1", name="Pond", enabled=True)
        device = make_mock_automower_device(
            has_stay_out_zones=True, stay_out_zones={"zone-1": zone}
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            # Entity references zone-99 which doesn't exist
            entity = AutomowerStayOutZoneSwitch(coordinator, device, "zone-99")
            assert entity.is_on is None

    async def test_work_area_native_value_none_when_area_missing(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """automower_number.py:133-135: native_value None when work area missing."""
        from custom_components.gardena_smart_system.automower_number import (
            AutomowerWorkAreaHeightEntity,
        )

        wa = WorkArea(work_area_id=1, name="Front Yard", cutting_height=60, enabled=True)
        device = make_mock_automower_device(has_work_areas=True, work_areas={1: wa})
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            # Entity references work_area_id=99 which doesn't exist
            entity = AutomowerWorkAreaHeightEntity(coordinator, device, 99)
            assert entity.native_value is None

    async def test_headlight_is_on_none_when_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """automower_switch.py:77-78: headlight is_on returns None."""
        from custom_components.gardena_smart_system.automower_switch import (
            AutomowerHeadlightSwitch,
        )

        device = make_mock_automower_device(has_headlights=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            entity = AutomowerHeadlightSwitch(coordinator, device)
            assert entity.is_on is None

    async def test_zone_is_on_none_when_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """automower_switch.py:135-136: zone is_on None when device itself is gone."""
        from custom_components.gardena_smart_system.automower_switch import (
            AutomowerStayOutZoneSwitch,
        )

        zone = StayOutZone(zone_id="zone-1", name="Pond", enabled=True)
        device = make_mock_automower_device(
            has_stay_out_zones=True, stay_out_zones={"zone-1": zone}
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            entity = AutomowerStayOutZoneSwitch(coordinator, device, "zone-1")
            assert entity.is_on is None

    async def test_cutting_height_native_value_none_when_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """automower_number.py:75-76: cutting height native_value None."""
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
            assert entity.native_value is None

    async def test_work_area_native_value_none_when_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """automower_number.py:131-132: work area native_value None when device gone."""
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
            assert entity.native_value is None


# ──────────────────────────────────────────────────────────────────────
# 20. Zone turn_off + Calendar async_get_events coverage
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerMiscCoverage:
    """Cover remaining uncovered lines."""

    async def test_zone_turn_off_calls_client(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """automower_switch.py:148: turn_off delegates to _async_set_zone(False)."""
        zone = StayOutZone(zone_id="zone-1", name="Pond", enabled=True)
        device = make_mock_automower_device(
            has_stay_out_zones=True, stay_out_zones={"zone-1": zone}
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            entity_id = _find_entity_id(hass, "switch", "soz_zone-1")
            await hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": entity_id},
                blocking=True,
            )

            mock_client.async_set_stay_out_zone.assert_called_once_with(
                device.mower_id, "zone-1", False
            )

    async def test_async_get_events_delegates_to_generate(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """automower_calendar.py:91: async_get_events calls _generate_events."""
        from homeassistant.util import dt as dt_util

        from custom_components.gardena_smart_system.automower_calendar import (
            AutomowerCalendarEntity,
        )

        task = ScheduleTask(
            start=480,
            duration=120,
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=True,
            sunday=True,
            work_area_id=None,
        )
        device = make_mock_automower_device(tasks=[task])
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            entity = AutomowerCalendarEntity(coordinator, device)
            entity.hass = hass

            start = datetime(2025, 6, 16, 0, 0, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
            end = datetime(2025, 6, 22, 23, 59, 59, tzinfo=dt_util.DEFAULT_TIME_ZONE)
            events = await entity.async_get_events(hass, start, end)
            assert len(events) == 7  # Every day of the week

    async def test_calendar_event_filter_skips_out_of_range(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """automower_calendar.py:117: tasks outside date range are skipped."""
        from homeassistant.util import dt as dt_util

        from custom_components.gardena_smart_system.automower_calendar import (
            AutomowerCalendarEntity,
        )

        # Task runs 8:00-10:00
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
            work_area_id=None,
        )
        device = make_mock_automower_device(tasks=[task])

        # Query window is 12:00-23:59 on Monday — task ends at 10:00, so it's skipped
        start = datetime(2025, 6, 16, 12, 0, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
        end = datetime(2025, 6, 16, 23, 59, 59, tzinfo=dt_util.DEFAULT_TIME_ZONE)
        events = AutomowerCalendarEntity._generate_events(device, start, end)
        assert len(events) == 0

    async def test_automower_options_flow(self, hass: HomeAssistant) -> None:
        """config_flow.py:481: Automower options flow omits watering/socket fields."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=AUTOMOWER_ENTRY_DATA,
            title="Automower",
            version=2,
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == "form"

        # Submit poll interval only (no watering/socket for automower)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={"poll_interval_minutes": 20},
        )
        assert result["type"] == "create_entry"
        assert entry.options["poll_interval_minutes"] == 20

    async def test_coordinator_location_id_property(self, hass: HomeAssistant) -> None:
        """coordinator.py:101: location_id returns the stored ID."""
        from .conftest import ENTRY_DATA, MOCK_LOCATION_ID, make_mock_device

        gardena_entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, title="My Garden")
        device = make_mock_device()
        devices = {device.device_id: device}

        _P_CLIENT = "custom_components.gardena_smart_system.coordinator.GardenaClient"
        _P_AUTH = "custom_components.gardena_smart_system.coordinator.GardenaAuth"
        _P_WS = "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"

        with patch(_P_CLIENT) as cls, patch(_P_AUTH), patch(_P_WS) as ws_cls:
            client = AsyncMock()
            client.async_get_devices = AsyncMock(return_value=devices)
            client.async_get_websocket_url = AsyncMock(return_value="wss://t")
            cls.return_value = client
            ws_cls.return_value = AsyncMock()

            gardena_entry.add_to_hass(hass)
            await hass.config_entries.async_setup(gardena_entry.entry_id)
            await hass.async_block_till_done()

        coordinator = gardena_entry.runtime_data
        assert coordinator.location_id == MOCK_LOCATION_ID


# ──────────────────────────────────────────────────────────────────────
# 21. Automower Event Entity
# ──────────────────────────────────────────────────────────────────────

EVENT_ENTITY_ID = "event.test_mower_mower_event"


class TestAutomowerEventEntity:
    """Test the Automower event entity fires on state transitions."""

    async def test_event_entity_created(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Event entity is created for each Automower device."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_reg = er.async_get(hass)
            event_entries = [
                e
                for e in entity_reg.entities.values()
                if e.domain == "event" and e.platform == DOMAIN
            ]
            assert len(event_entries) == 1
            assert event_entries[0].unique_id == "AM-SN-001_event"

    async def test_event_fires_on_activity_change_to_mowing(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Transition to MOWING fires started_mowing event."""
        device = make_mock_automower_device(mower_activity=MowerActivity.CHARGING)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            updated = make_mock_automower_device(mower_activity=MowerActivity.MOWING)
            coordinator.async_set_updated_data({device.mower_id: updated})
            await hass.async_block_till_done()

            state = hass.states.get(EVENT_ENTITY_ID)
            assert state is not None
            assert state.attributes["event_type"] == "started_mowing"

    async def test_event_fires_on_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Error state fires error event with error_code."""
        device = make_mock_automower_device(
            mower_state=MowerState.IN_OPERATION,
            mower_activity=MowerActivity.MOWING,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            error_device = make_mock_automower_device(
                mower_state=MowerState.ERROR,
                error_code=5,
            )
            coordinator.async_set_updated_data({device.mower_id: error_device})
            await hass.async_block_till_done()

            state = hass.states.get(EVENT_ENTITY_ID)
            assert state is not None
            assert state.attributes["event_type"] == "error"
            assert state.attributes["error_code"] == "5"

    async def test_event_fires_error_cleared(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Transition from error to normal fires error_cleared."""
        device = make_mock_automower_device(mower_state=MowerState.ERROR)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            ok_device = make_mock_automower_device(
                mower_state=MowerState.IN_OPERATION,
                mower_activity=MowerActivity.MOWING,
            )
            coordinator.async_set_updated_data({device.mower_id: ok_device})
            await hass.async_block_till_done()

            state = hass.states.get(EVENT_ENTITY_ID)
            assert state is not None
            assert state.attributes["event_type"] == "error_cleared"

    async def test_event_fires_going_home(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Transition to GOING_HOME fires going_home event."""
        device = make_mock_automower_device(mower_activity=MowerActivity.MOWING)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            updated = make_mock_automower_device(mower_activity=MowerActivity.GOING_HOME)
            coordinator.async_set_updated_data({device.mower_id: updated})
            await hass.async_block_till_done()

            state = hass.states.get(EVENT_ENTITY_ID)
            assert state is not None
            assert state.attributes["event_type"] == "going_home"

    async def test_event_fires_parked(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Transition to PARKED_IN_CS fires parked event."""
        device = make_mock_automower_device(mower_activity=MowerActivity.CHARGING)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            parked = make_mock_automower_device(mower_activity=MowerActivity.PARKED_IN_CS)
            coordinator.async_set_updated_data({device.mower_id: parked})
            await hass.async_block_till_done()

            state = hass.states.get(EVENT_ENTITY_ID)
            assert state is not None
            assert state.attributes["event_type"] == "parked"

    async def test_event_fires_paused_on_state_change(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """State change to PAUSED fires paused event."""
        device = make_mock_automower_device(
            mower_state=MowerState.IN_OPERATION,
            mower_activity=MowerActivity.MOWING,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            paused = make_mock_automower_device(
                mower_state=MowerState.PAUSED,
                mower_activity=MowerActivity.MOWING,
            )
            coordinator.async_set_updated_data({device.mower_id: paused})
            await hass.async_block_till_done()

            state = hass.states.get(EVENT_ENTITY_ID)
            assert state is not None
            assert state.attributes["event_type"] == "paused"

    async def test_no_event_when_state_unchanged(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """No event fires when nothing changed."""
        device = make_mock_automower_device(mower_activity=MowerActivity.MOWING)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            # Same state as before — no event should fire
            same = make_mock_automower_device(mower_activity=MowerActivity.MOWING)
            coordinator.async_set_updated_data({device.mower_id: same})
            await hass.async_block_till_done()

            state = hass.states.get(EVENT_ENTITY_ID)
            assert state is not None
            # Event entities show no event_type when none has fired
            assert state.attributes.get("event_type") is None

    async def test_no_event_when_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """No event fires when device disappears from coordinator."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            state = hass.states.get(EVENT_ENTITY_ID)
            assert state is not None
            assert state.attributes.get("event_type") is None

    async def test_event_fires_stopped(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Transition to STOPPED_IN_GARDEN fires stopped event."""
        device = make_mock_automower_device(mower_activity=MowerActivity.MOWING)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            stopped = make_mock_automower_device(mower_activity=MowerActivity.STOPPED_IN_GARDEN)
            coordinator.async_set_updated_data({device.mower_id: stopped})
            await hass.async_block_till_done()

            state = hass.states.get(EVENT_ENTITY_ID)
            assert state is not None
            assert state.attributes["event_type"] == "stopped"

    async def test_event_fires_charging(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Transition to CHARGING fires charging event."""
        device = make_mock_automower_device(mower_activity=MowerActivity.GOING_HOME)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            charging = make_mock_automower_device(mower_activity=MowerActivity.CHARGING)
            coordinator.async_set_updated_data({device.mower_id: charging})
            await hass.async_block_till_done()

            state = hass.states.get(EVENT_ENTITY_ID)
            assert state is not None
            assert state.attributes["event_type"] == "charging"

    async def test_event_fires_leaving(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Transition to LEAVING fires leaving event."""
        device = make_mock_automower_device(mower_activity=MowerActivity.PARKED_IN_CS)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data

            leaving = make_mock_automower_device(mower_activity=MowerActivity.LEAVING)
            coordinator.async_set_updated_data({device.mower_id: leaving})
            await hass.async_block_till_done()

            state = hass.states.get(EVENT_ENTITY_ID)
            assert state is not None
            assert state.attributes["event_type"] == "leaving"


# ──────────────────────────────────────────────────────────────────────
# 22. Automower Diagnostic Sensors (Feature 1)
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerDiagnosticSensors:
    """Test the new Automower diagnostic sensors (disabled by default)."""

    async def test_inactive_reason_sensor(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Inactive reason sensor reports the value from the API after enabling."""
        device = make_mock_automower_device(inactive_reason="PLANNING")
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "sensor", "inactive_reason")
            # Entity exists in registry but is disabled by default
            entity_reg = er.async_get(hass)
            entry = entity_reg.async_get(entity_id)
            assert entry is not None
            assert entry.disabled_by is not None

            # Enable it and reload
            entity_reg.async_update_entity(entity_id, disabled_by=None)
            await hass.config_entries.async_reload(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "PLANNING"

    async def test_inactive_reason_none(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Inactive reason sensor shows unknown when None."""
        device = make_mock_automower_device(inactive_reason=None)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "sensor", "inactive_reason")
            entity_reg = er.async_get(hass)
            entity_reg.async_update_entity(entity_id, disabled_by=None)
            await hass.config_entries.async_reload(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "unknown"

    async def test_restricted_reason_sensor(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Restricted reason sensor reports lowercased value."""
        device = make_mock_automower_device(restricted_reason="WEEK_SCHEDULE")
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "sensor", "restricted_reason")
            entity_reg = er.async_get(hass)
            entity_reg.async_update_entity(entity_id, disabled_by=None)
            await hass.config_entries.async_reload(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "week_schedule"

    async def test_error_code_timestamp_sensor(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Error code timestamp sensor reports the datetime."""
        ts = datetime(2026, 3, 20, 14, 30, 0, tzinfo=UTC)
        device = make_mock_automower_device(error_code_timestamp=ts)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "sensor", "error_code_timestamp")
            entity_reg = er.async_get(hass)
            entity_reg.async_update_entity(entity_id, disabled_by=None)
            await hass.config_entries.async_reload(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state != "unknown"

    async def test_error_code_timestamp_none(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Error code timestamp shows unknown when None."""
        device = make_mock_automower_device(error_code_timestamp=None)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "sensor", "error_code_timestamp")
            entity_reg = er.async_get(hass)
            entity_reg.async_update_entity(entity_id, disabled_by=None)
            await hass.config_entries.async_reload(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "unknown"


# ──────────────────────────────────────────────────────────────────────
# 23. Automower Work Area Switches (Feature 2)
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerWorkAreaSwitch:
    """Test the work area enable/disable switches."""

    async def test_work_area_switch_created(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Work area switch is created when work_areas capability is True."""
        wa = WorkArea(work_area_id=1, name="Front yard", cutting_height=5, enabled=True)
        device = make_mock_automower_device(has_work_areas=True, work_areas={1: wa})
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("switch.test_mower_work_area_front_yard")
            assert state is not None
            assert state.state == "on"

    async def test_work_area_switch_off(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Work area switch reports off when disabled."""
        wa = WorkArea(work_area_id=2, name="Back yard", cutting_height=3, enabled=False)
        device = make_mock_automower_device(has_work_areas=True, work_areas={2: wa})
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("switch.test_mower_work_area_back_yard")
            assert state is not None
            assert state.state == "off"

    async def test_work_area_switch_turn_on(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Turning on a work area calls the API."""
        wa = WorkArea(work_area_id=1, name="Front", cutting_height=5, enabled=False)
        device = make_mock_automower_device(has_work_areas=True, work_areas={1: wa})
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": "switch.test_mower_work_area_front"},
                blocking=True,
            )
            mock_client.async_set_work_area_enabled.assert_called_once_with(
                device.mower_id, 1, True
            )

    async def test_work_area_switch_turn_off(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Turning off a work area calls the API."""
        wa = WorkArea(work_area_id=1, name="Front", cutting_height=5, enabled=True)
        device = make_mock_automower_device(has_work_areas=True, work_areas={1: wa})
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            await hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": "switch.test_mower_work_area_front"},
                blocking=True,
            )
            mock_client.async_set_work_area_enabled.assert_called_once_with(
                device.mower_id, 1, False
            )

    async def test_work_area_switch_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Work area switch returns None when device disappears."""
        wa = WorkArea(work_area_id=1, name="Front", cutting_height=5, enabled=True)
        device = make_mock_automower_device(has_work_areas=True, work_areas={1: wa})
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            state = hass.states.get("switch.test_mower_work_area_front")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_work_area_switch_auth_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Auth error on work area switch raises ConfigEntryAuthFailed."""
        wa = WorkArea(work_area_id=1, name="Front", cutting_height=5, enabled=True)
        device = make_mock_automower_device(has_work_areas=True, work_areas={1: wa})
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            mock_client.async_set_work_area_enabled.side_effect = AutomowerAuthenticationError(
                "bad token"
            )
            with pytest.raises(Exception):
                await hass.services.async_call(
                    "switch",
                    "turn_on",
                    {"entity_id": "switch.test_mower_work_area_front"},
                    blocking=True,
                )


# ──────────────────────────────────────────────────────────────────────
# 24. Automower Confirm Error Button (Feature 4)
# ──────────────────────────────────────────────────────────────────────

BUTTON_ENTITY_ID = "button.test_mower_confirm_error"


class TestAutomowerConfirmErrorButton:
    """Test the Automower error confirmation button."""

    async def test_button_created_when_capable(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Button entity is created when can_confirm_error is True."""
        device = make_mock_automower_device(can_confirm_error=True, is_error_confirmable=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get(BUTTON_ENTITY_ID)
            assert state is not None

    async def test_button_not_created_when_incapable(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Button entity is NOT created when can_confirm_error is False."""
        device = make_mock_automower_device(can_confirm_error=False)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get(BUTTON_ENTITY_ID)
            assert state is None

    async def test_button_unavailable_when_no_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Button is unavailable when is_error_confirmable is False."""
        device = make_mock_automower_device(can_confirm_error=True, is_error_confirmable=False)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get(BUTTON_ENTITY_ID)
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_button_press_calls_api(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Pressing the button calls async_confirm_error."""
        device = make_mock_automower_device(
            can_confirm_error=True,
            is_error_confirmable=True,
            mower_state=MowerState.ERROR,
            error_code=5,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": BUTTON_ENTITY_ID},
                blocking=True,
            )
            mock_client.async_confirm_error.assert_called_once_with(device.mower_id)

    async def test_button_press_auth_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Auth error on button press raises appropriately."""
        device = make_mock_automower_device(
            can_confirm_error=True,
            is_error_confirmable=True,
            mower_state=MowerState.ERROR,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            mock_client.async_confirm_error.side_effect = AutomowerAuthenticationError("bad")
            with pytest.raises(Exception):
                await hass.services.async_call(
                    "button",
                    "press",
                    {"entity_id": BUTTON_ENTITY_ID},
                    blocking=True,
                )

    async def test_button_press_general_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """General API error on button press raises HomeAssistantError."""
        device = make_mock_automower_device(
            can_confirm_error=True,
            is_error_confirmable=True,
            mower_state=MowerState.ERROR,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            mock_client.async_confirm_error.side_effect = AutomowerException("fail")
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "button",
                    "press",
                    {"entity_id": BUTTON_ENTITY_ID},
                    blocking=True,
                )


# ──────────────────────────────────────────────────────────────────────
# Feature Tests: Schedule Override Number Entity
# ──────────────────────────────────────────────────────────────────────

SCHEDULE_OVERRIDE_ENTITY_ID = "number.test_mower_schedule_override"


class TestAutomowerScheduleOverride:
    """Test the Automower schedule override number entity."""

    async def test_schedule_override_entity_created(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_reg = er.async_get(hass)
            entry = entity_reg.async_get(SCHEDULE_OVERRIDE_ENTITY_ID)
            assert entry is not None
            assert entry.unique_id == "AM-SN-001_schedule_override"

    async def test_schedule_override_value_none_when_no_override(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(override_action="NOT_ACTIVE")
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get(SCHEDULE_OVERRIDE_ENTITY_ID)
            assert state is not None
            assert state.state == "unknown"

    async def test_schedule_override_value_when_force_mow(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(override_action="FORCE_MOW")
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get(SCHEDULE_OVERRIDE_ENTITY_ID)
            assert state is not None
            # native_value is None (no last_set_value) so state is unknown
            assert state.state == "unknown"

    async def test_schedule_override_set_value_calls_api(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            await hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": SCHEDULE_OVERRIDE_ENTITY_ID, "value": 60},
                blocking=True,
            )
            mock_client.async_start.assert_called_once_with(
                device.mower_id, duration=60
            )

    async def test_schedule_override_auth_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            mock_client.async_start.side_effect = AutomowerAuthenticationError("auth")
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": SCHEDULE_OVERRIDE_ENTITY_ID, "value": 30},
                    blocking=True,
                )

    async def test_schedule_override_generic_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            mock_client.async_start.side_effect = AutomowerException("fail")
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": SCHEDULE_OVERRIDE_ENTITY_ID, "value": 30},
                    blocking=True,
                )

    async def test_schedule_override_device_unavailable(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            # Remove device from coordinator data
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()

            state = hass.states.get(SCHEDULE_OVERRIDE_ENTITY_ID)
            assert state is not None
            assert state.state == "unavailable"


# ──────────────────────────────────────────────────────────────────────
# Feature Tests: Automower Error Code Sensor
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerErrorCodeSensor:
    """Test the Automower error code sensor."""

    async def test_error_code_sensor_created_disabled(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(error_code=42)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "sensor", "error_code")
            assert entity_id is not None
            entity_reg = er.async_get(hass)
            entry = entity_reg.async_get(entity_id)
            assert entry is not None
            assert entry.disabled_by is not None

    async def test_error_code_sensor_value_after_enable(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(error_code=42)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "sensor", "error_code")
            entity_reg = er.async_get(hass)
            entity_reg.async_update_entity(entity_id, disabled_by=None)
            await hass.config_entries.async_reload(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "42"

    async def test_error_code_zero(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(error_code=0)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_id = _find_entity_id(hass, "sensor", "error_code")
            entity_reg = er.async_get(hass)
            entity_reg.async_update_entity(entity_id, disabled_by=None)
            await hass.config_entries.async_reload(automower_config_entry.entry_id)
            await hass.async_block_till_done()

            state = hass.states.get(entity_id)
            assert state is not None
            assert state.state == "0"


# ──────────────────────────────────────────────────────────────────────
# Feature Tests: Extended Diagnostics
# ──────────────────────────────────────────────────────────────────────


class TestExtendedDiagnostics:
    """Test the extended diagnostics output."""

    async def test_diagnostics_has_extended_fields(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        from custom_components.gardena_smart_system.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            result = await async_get_config_entry_diagnostics(hass, automower_config_entry)

            coordinator_data = result["coordinator"]
            assert "ws_connected" in coordinator_data
            assert "device_count" in coordinator_data
            assert coordinator_data["device_count"] == 1
            assert "diagnostics_generated_at" in coordinator_data
            assert "stale_miss_counts" in coordinator_data
            assert "last_command_time_monotonic" in coordinator_data


# ──────────────────────────────────────────────────────────────────────
# Feature Tests: Hub Dashboard Entities (Automower)
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerHubEntities:
    """Test hub-level diagnostic entities for Automower."""

    async def test_hub_device_count_sensor(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_reg = er.async_get(hass)
            found = None
            for entry in entity_reg.entities.values():
                if "device_count" in (entry.unique_id or ""):
                    found = entry
                    break
            assert found is not None
            state = hass.states.get(found.entity_id)
            assert state is not None
            assert int(state.state) == 1

    async def test_hub_polling_interval_sensor(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_reg = er.async_get(hass)
            found = None
            for entry in entity_reg.entities.values():
                if "polling_interval" in (entry.unique_id or ""):
                    found = entry
                    break
            assert found is not None
            state = hass.states.get(found.entity_id)
            assert state is not None
            assert float(state.state) > 0

    async def test_hub_websocket_binary_sensor(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            entity_reg = er.async_get(hass)
            found = None
            for entry in entity_reg.entities.values():
                if "websocket_connected" in (entry.unique_id or ""):
                    found = entry
                    break
            assert found is not None
            state = hass.states.get(found.entity_id)
            assert state is not None
            assert state.state == "on"


# ──────────────────────────────────────────────────────────────────────
# v1.3.0 Features: P1, P3, P5, P6
# ──────────────────────────────────────────────────────────────────────


class TestAutomowerTotalChargingTime:
    """P1: Total charging time sensor."""

    async def test_total_charging_time_value(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Sensor shows total_charging_time in hours (integer division)."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("sensor.test_mower_total_charging_time")
            assert state is not None
            # 10000 seconds // 3600 = 2 hours
            assert state.state == "2"


class TestAutomowerPlannerOverrideSensor:
    """P5: Planner override enum sensor."""

    async def test_override_not_active(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(override_action="NOT_ACTIVE")
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("sensor.test_mower_schedule_override")
            assert state is not None
            assert state.state == "not_active"

    async def test_override_force_mow(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(override_action="FORCE_MOW")
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("sensor.test_mower_schedule_override")
            assert state is not None
            assert state.state == "force_mow"


class TestAutomowerLastSeenSensor:
    """P6: Last seen timestamp sensor."""

    async def test_last_seen_value(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("sensor.test_mower_last_seen")
            assert state is not None
            assert "2025-06-15" in state.state


class TestAutomowerModeSensor:
    """P8: Automower operating mode enum sensor."""

    async def test_mode_sensor_created(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Mode sensor is created with correct value."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("sensor.test_mower_operating_mode")
            assert state is not None
            assert state.state == "main_area"

    async def test_mode_sensor_home(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Mode sensor shows HOME when mower is returning."""
        device = make_mock_automower_device(mower_mode="HOME")
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("sensor.test_mower_operating_mode")
            assert state is not None
            assert state.state == "home"


class TestAutomowerHeadlightSelect:
    """P3: Headlight mode select entity."""

    async def test_select_entity_created(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            has_headlights=True, headlight_mode="ALWAYS_OFF"
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("select.test_mower_headlight_mode")
            assert state is not None
            assert state.state == "always_off"

    async def test_select_always_on(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            has_headlights=True, headlight_mode="ALWAYS_ON"
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("select.test_mower_headlight_mode")
            assert state is not None
            assert state.state == "always_on"

    async def test_select_evening_only(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            has_headlights=True, headlight_mode="EVENING_ONLY"
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("select.test_mower_headlight_mode")
            assert state is not None
            assert state.state == "evening_only"

    async def test_select_set_option_calls_api(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(
            has_headlights=True, headlight_mode="ALWAYS_OFF"
        )
        devices = {device.mower_id: device}

        async with _setup_automower(
            hass, automower_config_entry, devices
        ) as mock_client:
            await hass.services.async_call(
                "select",
                "select_option",
                {
                    "entity_id": "select.test_mower_headlight_mode",
                    "option": "evening_and_night",
                },
                blocking=True,
            )
            mock_client.async_set_headlight_mode.assert_called_once_with(
                device.mower_id, "EVENING_AND_NIGHT"
            )

    async def test_no_select_without_headlight_capability(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        device = make_mock_automower_device(has_headlights=False)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            state = hass.states.get("select.test_mower_headlight_mode")
            assert state is None

    async def test_select_device_removed(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Select current_option returns None when device removed."""
        device = make_mock_automower_device(has_headlights=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            # Remove device from coordinator data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()
            state = hass.states.get("select.test_mower_headlight_mode")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_select_option_device_gone_unavailable(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Select entity is unavailable when device removed — covers current_option None path."""
        device = make_mock_automower_device(has_headlights=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()
            state = hass.states.get("select.test_mower_headlight_mode")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_select_option_auth_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Select async_select_option raises on auth error."""
        device = make_mock_automower_device(has_headlights=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            mock_client.async_set_headlight_mode.side_effect = AutomowerAuthenticationError("auth fail")
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "select",
                    "select_option",
                    {"entity_id": "select.test_mower_headlight_mode", "option": "always_on"},
                    blocking=True,
                )

    async def test_select_option_generic_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Select async_select_option raises on generic error."""
        device = make_mock_automower_device(has_headlights=True)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            mock_client.async_set_headlight_mode.side_effect = AutomowerException("fail")
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "select",
                    "select_option",
                    {"entity_id": "select.test_mower_headlight_mode", "option": "always_on"},
                    blocking=True,
                )


class TestAutomowerNoneGuards:
    """Test device-removed / None guard branches across automower platforms."""

    async def test_button_available_false_when_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Confirm error button returns unavailable when device removed."""
        device = make_mock_automower_device(
            is_error_confirmable=True, can_confirm_error=True,
            mower_state=MowerState.ERROR, error_code=1,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()
            state = hass.states.get("button.test_mower_confirm_error")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_button_press_device_gone_unavailable(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Confirm error button is unavailable when device removed."""
        device = make_mock_automower_device(
            is_error_confirmable=True, can_confirm_error=True,
            mower_state=MowerState.ERROR, error_code=1,
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()
            state = hass.states.get("button.test_mower_confirm_error")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_number_value_none_when_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Schedule override number returns unavailable when device removed."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()
            state = hass.states.get("number.test_mower_schedule_override")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_number_set_device_gone_unavailable(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Schedule override number is unavailable when device removed."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()
            state = hass.states.get("number.test_mower_schedule_override")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_work_area_switch_device_gone(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Work area switch returns unavailable when device removed."""
        device = make_mock_automower_device(
            has_work_areas=True,
            work_areas={1: WorkArea(work_area_id=1, name="Front Lawn", cutting_height=50, enabled=True)},
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()
            state = hass.states.get("switch.test_mower_work_area_front_lawn")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_work_area_switch_area_removed(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Work area switch returns None when work area removed from device."""
        device = make_mock_automower_device(
            has_work_areas=True,
            work_areas={1: WorkArea(work_area_id=1, name="Front Lawn", cutting_height=50, enabled=True)},
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            # Update device with work_areas empty
            updated = make_mock_automower_device(
                has_work_areas=True, work_areas={},
            )
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({device.mower_id: updated})
            await hass.async_block_till_done()
            state = hass.states.get("switch.test_mower_work_area_front_lawn")
            assert state is not None
            # is_on returns None → unknown
            assert state.state in ("unknown", STATE_UNAVAILABLE)

    async def test_work_area_switch_set_device_gone_unavailable(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Work area switch is unavailable when device removed."""
        device = make_mock_automower_device(
            has_work_areas=True,
            work_areas={1: WorkArea(work_area_id=1, name="Front Lawn", cutting_height=50, enabled=False)},
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            coordinator.async_set_updated_data({})
            await hass.async_block_till_done()
            state = hass.states.get("switch.test_mower_work_area_front_lawn")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE

    async def test_work_area_switch_auth_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Work area switch raises on auth error."""
        device = make_mock_automower_device(
            has_work_areas=True,
            work_areas={1: WorkArea(work_area_id=1, name="Front Lawn", cutting_height=50, enabled=False)},
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            mock_client.async_set_work_area_enabled.side_effect = AutomowerAuthenticationError("auth")
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "switch",
                    "turn_on",
                    {"entity_id": "switch.test_mower_work_area_front_lawn"},
                    blocking=True,
                )

    async def test_work_area_switch_generic_error(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Work area switch raises on generic error."""
        device = make_mock_automower_device(
            has_work_areas=True,
            work_areas={1: WorkArea(work_area_id=1, name="Front Lawn", cutting_height=50, enabled=False)},
        )
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            mock_client.async_set_work_area_enabled.side_effect = AutomowerException("fail")
            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "switch",
                    "turn_on",
                    {"entity_id": "switch.test_mower_work_area_front_lawn"},
                    blocking=True,
                )

    async def test_entity_device_none_coordinator_data_none(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Entity _device returns None when coordinator.data is None."""
        device = make_mock_automower_device()
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices):
            coordinator = automower_config_entry.runtime_data
            # Set data to None (simulates coordinator failure)
            coordinator.data = None
            coordinator.async_set_updated_data(None)
            await hass.async_block_till_done()
            state = hass.states.get("sensor.test_mower_battery")
            assert state is not None
            assert state.state == STATE_UNAVAILABLE
