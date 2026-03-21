"""Binary sensor platform for Automower devices."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from aioautomower import AutomowerDevice
from aioautomower.const import MowerState

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GardenaConfigEntry
from .automower_coordinator import AutomowerCoordinator
from .automower_entity import AutomowerEntity
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AutomowerBinarySensorDescription(BinarySensorEntityDescription):
    """Describes an Automower binary sensor."""

    is_on_fn: Callable[[AutomowerDevice], bool | None]


BINARY_SENSOR_DESCRIPTIONS: tuple[AutomowerBinarySensorDescription, ...] = (
    AutomowerBinarySensorDescription(
        key="error",
        translation_key="automower_error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: d.mower.state in (MowerState.ERROR, MowerState.FATAL_ERROR),
    ),
    AutomowerBinarySensorDescription(
        key="connected",
        translation_key="automower_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda d: d.metadata.connected,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Automower binary sensor entities from a config entry."""
    if entry.data.get(CONF_API_TYPE) != API_TYPE_AUTOMOWER:
        return

    coordinator: AutomowerCoordinator = entry.runtime_data
    known_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        new_entities: list[AutomowerBinarySensorEntity] = []
        for device in coordinator.data.values():
            for desc in BINARY_SENSOR_DESCRIPTIONS:
                entity_key = f"{device.mower_id}_{desc.key}"
                if entity_key not in known_ids:
                    known_ids.add(entity_key)
                    new_entities.append(
                        AutomowerBinarySensorEntity(coordinator, device, desc)
                    )
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()


class AutomowerBinarySensorEntity(AutomowerEntity, BinarySensorEntity):
    """Represents an Automower binary sensor."""

    entity_description: AutomowerBinarySensorDescription

    def __init__(
        self,
        coordinator: AutomowerCoordinator,
        device: AutomowerDevice,
        description: AutomowerBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the binary sensor value."""
        device = self._device
        if device is None:
            return None
        return self.entity_description.is_on_fn(device)
