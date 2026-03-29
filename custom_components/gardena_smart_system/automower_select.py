"""Select platform for Automower headlight mode."""

from __future__ import annotations

from typing import cast

from aioautomower.const import HeadlightMode
from aioautomower.exceptions import AutomowerAuthenticationError, AutomowerException
from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from aioautomower import AutomowerDevice

from . import GardenaConfigEntry
from .automower_coordinator import AutomowerCoordinator
from .automower_entity import AutomowerEntity
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE

PARALLEL_UPDATES = 1

HEADLIGHT_OPTIONS = [
    HeadlightMode.ALWAYS_ON,
    HeadlightMode.ALWAYS_OFF,
    HeadlightMode.EVENING_ONLY,
    HeadlightMode.EVENING_AND_NIGHT,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Automower select entities."""
    if entry.data.get(CONF_API_TYPE) != API_TYPE_AUTOMOWER:
        return

    coordinator = cast(AutomowerCoordinator, entry.runtime_data)
    known_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        if coordinator.data is None:
            return  # type: ignore[unreachable]
        new_entities: list[SelectEntity] = []
        for device in coordinator.data.values():
            if device.capabilities.headlights:
                key = f"{device.mower_id}_headlight_mode"
                if key not in known_ids:
                    known_ids.add(key)
                    new_entities.append(AutomowerHeadlightSelect(coordinator, device))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()


class AutomowerHeadlightSelect(AutomowerEntity, SelectEntity):
    """Select entity for Automower headlight mode."""

    _attr_translation_key = "automower_headlight_mode"

    def __init__(self, coordinator: AutomowerCoordinator, device: AutomowerDevice) -> None:
        """Initialize the headlight select."""
        super().__init__(coordinator, device, "headlight_mode")
        self._attr_options = [o.lower() for o in HEADLIGHT_OPTIONS]

    @property
    def current_option(self) -> str | None:
        """Return the current headlight mode."""
        device = self._device
        if device is None:
            return None
        return device.settings.headlight_mode.lower()

    async def async_select_option(self, option: str) -> None:
        """Set the headlight mode."""
        device = self._device
        if device is None:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="device_unavailable",
            )
        self.coordinator.check_command_throttle()
        mode = option.upper()
        try:
            await self.coordinator.client.async_set_headlight_mode(device.mower_id, mode)
        except AutomowerAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain="gardena_smart_system",
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except AutomowerException as err:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
