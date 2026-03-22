"""Sensor platform for Automower devices."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from aioautomower import AutomowerDevice

from aioautomower.const import MowerActivity, MowerState

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GardenaConfigEntry
from .automower_coordinator import AutomowerCoordinator
from .automower_entity import AutomowerEntity
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AutomowerSensorDescription(SensorEntityDescription):
    """Describes an Automower sensor."""

    value_fn: Callable[[AutomowerDevice], int | float | datetime | None]


SENSOR_DESCRIPTIONS: tuple[AutomowerSensorDescription, ...] = (
    AutomowerSensorDescription(
        key="battery_level",
        translation_key="automower_battery_level",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.battery.level,
    ),
    AutomowerSensorDescription(
        key="cutting_height",
        translation_key="automower_cutting_height",
        state_class=SensorStateClass.MEASUREMENT,
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
        value_fn=lambda d: d.mower.activity.lower(),
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
        value_fn=lambda d: d.mower.state.lower(),
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
                    new_entities.append(
                        AutomowerSensorEntity(coordinator, device, desc)
                    )
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
    def native_value(self) -> int | float | datetime | None:
        """Return the sensor value."""
        device = self._device
        if device is None:
            return None
        return self.entity_description.value_fn(device)
