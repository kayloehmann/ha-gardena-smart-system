"""Sensor platform for Automower devices."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from aioautomower.const import MowerActivity, MowerState, OverrideAction, RestrictedReason
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from aioautomower import AutomowerDevice

from . import GardenaConfigEntry
from .automower_coordinator import AutomowerCoordinator
from .automower_entity import AutomowerEntity
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE

PARALLEL_UPDATES = 0

_KNOWN_ACTIVITIES = frozenset(
    a.lower()
    for a in (
        MowerActivity.UNKNOWN,
        MowerActivity.NOT_APPLICABLE,
        MowerActivity.MOWING,
        MowerActivity.GOING_HOME,
        MowerActivity.CHARGING,
        MowerActivity.LEAVING,
        MowerActivity.PARKED_IN_CS,
        MowerActivity.STOPPED_IN_GARDEN,
    )
)
_KNOWN_RESTRICTED_REASONS = frozenset(
    r.lower()
    for r in (
        RestrictedReason.NONE,
        RestrictedReason.WEEK_SCHEDULE,
        RestrictedReason.PARK_OVERRIDE,
        RestrictedReason.SENSOR,
        RestrictedReason.DAILY_LIMIT,
        RestrictedReason.FOTA,
        RestrictedReason.FROST,
        RestrictedReason.ALL_WORK_AREAS_COMPLETED,
        RestrictedReason.EXTERNAL,
        RestrictedReason.NOT_APPLICABLE,
    )
)
_KNOWN_STATES = frozenset(
    s.lower()
    for s in (
        MowerState.UNKNOWN,
        MowerState.NOT_APPLICABLE,
        MowerState.PAUSED,
        MowerState.IN_OPERATION,
        MowerState.WAIT_UPDATING,
        MowerState.WAIT_POWER_UP,
        MowerState.RESTRICTED,
        MowerState.OFF,
        MowerState.STOPPED,
        MowerState.ERROR,
        MowerState.FATAL_ERROR,
        MowerState.ERROR_AT_POWER_UP,
    )
)


@dataclass(frozen=True, kw_only=True)
class AutomowerSensorDescription(SensorEntityDescription):
    """Describes an Automower sensor."""

    value_fn: Callable[[AutomowerDevice], int | float | datetime | str | None]


SENSOR_DESCRIPTIONS: tuple[AutomowerSensorDescription, ...] = (
    AutomowerSensorDescription(
        key="battery_level",
        translation_key="automower_battery_level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.battery.level,
    ),
    AutomowerSensorDescription(
        key="cutting_height",
        translation_key="automower_cutting_height",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.settings.cutting_height,
    ),
    AutomowerSensorDescription(
        key="next_start",
        translation_key="automower_next_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: d.planner.next_start_timestamp,
    ),
    AutomowerSensorDescription(
        key="total_cutting_time",
        translation_key="automower_total_cutting_time",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.statistics.total_cutting_time // 3600,
    ),
    AutomowerSensorDescription(
        key="total_charging_cycles",
        translation_key="automower_total_charging_cycles",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.statistics.number_of_charging_cycles,
    ),
    AutomowerSensorDescription(
        key="total_collisions",
        translation_key="automower_total_collisions",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.statistics.number_of_collisions,
    ),
    AutomowerSensorDescription(
        key="total_drive_distance",
        translation_key="automower_total_drive_distance",
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.statistics.total_drive_distance,
    ),
    AutomowerSensorDescription(
        key="blade_usage_time",
        translation_key="automower_blade_usage_time",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.statistics.cutting_blade_usage_time // 3600,
    ),
    AutomowerSensorDescription(
        key="total_running_time",
        translation_key="automower_total_running_time",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.statistics.total_running_time // 3600,
    ),
    AutomowerSensorDescription(
        key="total_searching_time",
        translation_key="automower_total_searching_time",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.statistics.total_searching_time // 3600,
    ),
    AutomowerSensorDescription(
        key="activity",
        translation_key="automower_activity",
        device_class=SensorDeviceClass.ENUM,
        options=[
            MowerActivity.UNKNOWN.lower(),
            MowerActivity.NOT_APPLICABLE.lower(),
            MowerActivity.MOWING.lower(),
            MowerActivity.GOING_HOME.lower(),
            MowerActivity.CHARGING.lower(),
            MowerActivity.LEAVING.lower(),
            MowerActivity.PARKED_IN_CS.lower(),
            MowerActivity.STOPPED_IN_GARDEN.lower(),
        ],
        value_fn=lambda d: (
            d.mower.activity.lower() if d.mower.activity.lower() in _KNOWN_ACTIVITIES else None
        ),
    ),
    AutomowerSensorDescription(
        key="state",
        translation_key="automower_state",
        device_class=SensorDeviceClass.ENUM,
        options=[
            MowerState.UNKNOWN.lower(),
            MowerState.NOT_APPLICABLE.lower(),
            MowerState.PAUSED.lower(),
            MowerState.IN_OPERATION.lower(),
            MowerState.WAIT_UPDATING.lower(),
            MowerState.WAIT_POWER_UP.lower(),
            MowerState.RESTRICTED.lower(),
            MowerState.OFF.lower(),
            MowerState.STOPPED.lower(),
            MowerState.ERROR.lower(),
            MowerState.FATAL_ERROR.lower(),
            MowerState.ERROR_AT_POWER_UP.lower(),
        ],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            d.mower.state.lower() if d.mower.state.lower() in _KNOWN_STATES else None
        ),
    ),
    AutomowerSensorDescription(
        key="inactive_reason",
        translation_key="automower_inactive_reason",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.mower.inactive_reason,
    ),
    AutomowerSensorDescription(
        key="restricted_reason",
        translation_key="automower_restricted_reason",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        options=[
            RestrictedReason.NONE.lower(),
            RestrictedReason.WEEK_SCHEDULE.lower(),
            RestrictedReason.PARK_OVERRIDE.lower(),
            RestrictedReason.SENSOR.lower(),
            RestrictedReason.DAILY_LIMIT.lower(),
            RestrictedReason.FOTA.lower(),
            RestrictedReason.FROST.lower(),
            RestrictedReason.ALL_WORK_AREAS_COMPLETED.lower(),
            RestrictedReason.EXTERNAL.lower(),
            RestrictedReason.NOT_APPLICABLE.lower(),
        ],
        value_fn=lambda d: (
            d.planner.restricted_reason.lower()
            if d.planner.restricted_reason.lower() in _KNOWN_RESTRICTED_REASONS
            else None
        ),
    ),
    AutomowerSensorDescription(
        key="error_code",
        translation_key="automower_error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.mower.error_code,
    ),
    AutomowerSensorDescription(
        key="error_code_timestamp",
        translation_key="automower_error_code_timestamp",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.mower.error_code_timestamp,
    ),
    # P1: Total charging time
    AutomowerSensorDescription(
        key="total_charging_time",
        translation_key="automower_total_charging_time",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.statistics.total_charging_time // 3600,
    ),
    # P5: Planner override action
    AutomowerSensorDescription(
        key="planner_override",
        translation_key="automower_planner_override",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=[
            OverrideAction.NOT_ACTIVE.lower(),
            OverrideAction.FORCE_PARK.lower(),
            OverrideAction.FORCE_MOW.lower(),
        ],
        value_fn=lambda d: d.planner.override.action.lower(),
    ),
    # P6: Last seen timestamp
    AutomowerSensorDescription(
        key="last_seen",
        translation_key="automower_last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.metadata.status_timestamp,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Automower sensor entities from a config entry."""
    if entry.data.get(CONF_API_TYPE) != API_TYPE_AUTOMOWER:
        return

    coordinator: AutomowerCoordinator = entry.runtime_data
    known_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        new_entities: list[AutomowerSensorEntity] = []
        for device in coordinator.data.values():
            for desc in SENSOR_DESCRIPTIONS:
                entity_key = f"{device.mower_id}_{desc.key}"
                if entity_key not in known_ids:
                    known_ids.add(entity_key)
                    new_entities.append(AutomowerSensorEntity(coordinator, device, desc))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()


class AutomowerSensorEntity(AutomowerEntity, SensorEntity):
    """Represents an Automower sensor."""

    entity_description: AutomowerSensorDescription

    def __init__(
        self,
        coordinator: AutomowerCoordinator,
        device: AutomowerDevice,
        description: AutomowerSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> int | float | datetime | str | None:
        """Return the sensor value."""
        device = self._device
        if device is None:
            return None
        return self.entity_description.value_fn(device)
