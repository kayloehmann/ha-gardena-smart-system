"""Sensor platform for the Gardena Smart System integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiogardenasmart import Device

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GardenaConfigEntry
from .coordinator import GardenaCoordinator
from .entity import GardenaEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GardenaSensorDescription(SensorEntityDescription):
    """Sensor description with a typed value extractor."""

    value_fn: Callable[[Device], Any]
    exists_fn: Callable[[Device], bool] = lambda _: True


COMMON_SENSORS: tuple[GardenaSensorDescription, ...] = (
    GardenaSensorDescription(
        key="battery_level",
        translation_key="battery_level",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.common.battery_level if d.common else None,
        exists_fn=lambda d: d.common is not None and d.common.battery_level is not None,
    ),
    GardenaSensorDescription(
        key="rf_link_level",
        translation_key="rf_link_level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.common.rf_link_level if d.common else None,
        exists_fn=lambda d: d.common is not None and d.common.rf_link_level is not None,
    ),
)

SENSOR_SENSORS: tuple[GardenaSensorDescription, ...] = (
    GardenaSensorDescription(
        key="soil_humidity",
        translation_key="soil_humidity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.MOISTURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.sensor.soil_humidity if d.sensor else None,
        exists_fn=lambda d: d.sensor is not None and d.sensor.soil_humidity is not None,
    ),
    GardenaSensorDescription(
        key="soil_temperature",
        translation_key="soil_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.sensor.soil_temperature if d.sensor else None,
        exists_fn=lambda d: d.sensor is not None and d.sensor.soil_temperature is not None,
    ),
    GardenaSensorDescription(
        key="ambient_temperature",
        translation_key="ambient_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.sensor.ambient_temperature if d.sensor else None,
        exists_fn=lambda d: (
            d.sensor is not None and d.sensor.ambient_temperature is not None
        ),
    ),
    GardenaSensorDescription(
        key="light_intensity",
        translation_key="light_intensity",
        native_unit_of_measurement="lx",
        device_class=SensorDeviceClass.ILLUMINANCE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.sensor.light_intensity if d.sensor else None,
        exists_fn=lambda d: (
            d.sensor is not None and d.sensor.light_intensity is not None
        ),
    ),
)

MOWER_SENSORS: tuple[GardenaSensorDescription, ...] = (
    GardenaSensorDescription(
        key="mower_operating_hours",
        translation_key="mower_operating_hours",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.mower.operating_hours if d.mower else None,
        exists_fn=lambda d: d.mower is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gardena sensor entities from a config entry."""
    coordinator = entry.runtime_data
    known_keys: set[tuple[str, str]] = set()

    @callback
    def _async_add_new_entities() -> None:
        new_entities: list[GardenaSensorEntity] = []
        for device in coordinator.data.values():
            for description in (*COMMON_SENSORS, *SENSOR_SENSORS, *MOWER_SENSORS):
                key = (device.device_id, description.key)
                if key not in known_keys and description.exists_fn(device):
                    known_keys.add(key)
                    new_entities.append(
                        GardenaSensorEntity(coordinator, device, description)
                    )
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()


class GardenaSensorEntity(GardenaEntity, SensorEntity):
    """A sensor entity for Gardena Smart System devices."""

    entity_description: GardenaSensorDescription

    def __init__(
        self,
        coordinator: GardenaCoordinator,
        device: Device,
        description: GardenaSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        device = self._device
        if device is None:
            return None
        return self.entity_description.value_fn(device)
