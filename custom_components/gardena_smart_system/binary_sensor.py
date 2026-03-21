"""Binary sensor platform for the Gardena Smart System integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from aiogardenasmart import Device
from aiogardenasmart.const import BatteryState, ServiceState

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GardenaConfigEntry
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE
from .coordinator import GardenaCoordinator
from .entity import GardenaEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GardenaBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor description with a typed value extractor."""

    is_on_fn: Callable[[Device], bool | None]
    exists_fn: Callable[[Device], bool] = lambda _: True


BINARY_SENSORS: tuple[GardenaBinarySensorDescription, ...] = (
    GardenaBinarySensorDescription(
        key="battery_low",
        translation_key="battery_low",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: (
            d.common.battery_state in (BatteryState.LOW, BatteryState.REPLACE_NOW)
            if d.common
            else None
        ),
        exists_fn=lambda d: d.common is not None and d.common.battery_state is not None,
    ),
    GardenaBinarySensorDescription(
        key="valve_error",
        translation_key="valve_error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda d: (
            any(
                v.state in (ServiceState.WARNING, ServiceState.ERROR)
                for v in d.valves.values()
            )
            if d.valves
            else None
        ),
        exists_fn=lambda d: bool(d.valves),
    ),
    GardenaBinarySensorDescription(
        key="mower_error",
        translation_key="mower_error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: (
            d.mower.state in (ServiceState.WARNING, ServiceState.ERROR)
            if d.mower
            else None
        ),
        exists_fn=lambda d: d.mower is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gardena binary sensor entities from a config entry."""
    if entry.data.get(CONF_API_TYPE) == API_TYPE_AUTOMOWER:
        from .automower_binary_sensor import async_setup_entry as automower_setup

        await automower_setup(hass, entry, async_add_entities)
        return

    coordinator = entry.runtime_data
    known_keys: set[tuple[str, str]] = set()

    @callback
    def _async_add_new_entities() -> None:
        new_entities: list[GardenaBinarySensorEntity] = []
        for device in coordinator.data.values():
            for description in BINARY_SENSORS:
                key = (device.device_id, description.key)
                if key not in known_keys and description.exists_fn(device):
                    known_keys.add(key)
                    new_entities.append(
                        GardenaBinarySensorEntity(coordinator, device, description)
                    )
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()


class GardenaBinarySensorEntity(GardenaEntity, BinarySensorEntity):
    """A binary sensor entity for Gardena Smart System devices."""

    entity_description: GardenaBinarySensorDescription

    def __init__(
        self,
        coordinator: GardenaCoordinator,
        device: Device,
        description: GardenaBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the sensor state."""
        device = self._device
        if device is None:
            return None
        return self.entity_description.is_on_fn(device)
