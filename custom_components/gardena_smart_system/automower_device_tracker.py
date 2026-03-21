"""Device tracker platform for Automower GPS position."""

from __future__ import annotations

from aioautomower import AutomowerDevice

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GardenaConfigEntry
from .automower_coordinator import AutomowerCoordinator
from .automower_entity import AutomowerEntity
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Automower device tracker entities."""
    if entry.data.get(CONF_API_TYPE) != API_TYPE_AUTOMOWER:
        return

    coordinator: AutomowerCoordinator = entry.runtime_data
    known_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        new_entities: list[AutomowerTrackerEntity] = []
        for device in coordinator.data.values():
            if (
                device.mower_id not in known_ids
                and device.capabilities.position
            ):
                known_ids.add(device.mower_id)
                new_entities.append(
                    AutomowerTrackerEntity(coordinator, device)
                )
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()


class AutomowerTrackerEntity(AutomowerEntity, TrackerEntity):
    """GPS position tracker for an Automower."""

    _attr_translation_key = "automower_position"

    def __init__(
        self, coordinator: AutomowerCoordinator, device: AutomowerDevice
    ) -> None:
        """Initialize the tracker entity."""
        super().__init__(coordinator, device, "position")

    @property
    def source_type(self) -> SourceType:
        """Return the source type."""
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Return latitude from the most recent position."""
        device = self._device
        if device is None or not device.positions:
            return None
        return device.positions[0].latitude

    @property
    def longitude(self) -> float | None:
        """Return longitude from the most recent position."""
        device = self._device
        if device is None or not device.positions:
            return None
        return device.positions[0].longitude
