"""Button platform for Automower devices."""

from __future__ import annotations

from typing import cast

from aioautomower.exceptions import AutomowerAuthenticationError, AutomowerException
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from aioautomower import AutomowerDevice

from . import GardenaConfigEntry
from .automower_coordinator import AutomowerCoordinator
from .automower_entity import AutomowerEntity
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Automower button entities."""
    if entry.data.get(CONF_API_TYPE) != API_TYPE_AUTOMOWER:
        return

    coordinator = cast(AutomowerCoordinator, entry.runtime_data)
    known_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        if coordinator.data is None:
            return  # type: ignore[unreachable]
        new_entities: list[ButtonEntity] = []
        for device in coordinator.data.values():
            if device.capabilities.can_confirm_error:
                key = f"{device.mower_id}_confirm_error"
                if key not in known_ids:
                    known_ids.add(key)
                    new_entities.append(AutomowerConfirmErrorButton(coordinator, device))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()


class AutomowerConfirmErrorButton(AutomowerEntity, ButtonEntity):
    """Button to confirm a confirmable error on the Automower."""

    _attr_translation_key = "automower_confirm_error"

    def __init__(self, coordinator: AutomowerCoordinator, device: AutomowerDevice) -> None:
        """Initialize the confirm error button."""
        super().__init__(coordinator, device, "confirm_error")

    @property
    def available(self) -> bool:
        """Only available when there is a confirmable error."""
        device = self._device
        if device is None:
            return False
        return super().available and device.mower.is_error_confirmable

    async def async_press(self) -> None:
        """Confirm the current error."""
        device = self._device
        if device is None:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="device_unavailable",
            )
        self.coordinator.check_command_throttle()
        try:
            await self.coordinator.client.async_confirm_error(device.mower_id)
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
