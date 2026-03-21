"""Number platform for Automower cutting height control."""

from __future__ import annotations

from aioautomower import AutomowerDevice
from aioautomower.exceptions import AutomowerAuthenticationError, AutomowerException

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
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
    """Set up Automower number entities."""
    if entry.data.get(CONF_API_TYPE) != API_TYPE_AUTOMOWER:
        return

    coordinator: AutomowerCoordinator = entry.runtime_data
    known_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        new_entities: list[NumberEntity] = []
        for device in coordinator.data.values():
            # Global cutting height
            key = f"{device.mower_id}_cutting_height"
            if key not in known_ids:
                known_ids.add(key)
                new_entities.append(
                    AutomowerCuttingHeightEntity(coordinator, device)
                )
            # Per-work-area cutting height
            if device.capabilities.work_areas:
                for wa in device.work_areas.values():
                    wa_key = f"{device.mower_id}_wa_{wa.work_area_id}_height"
                    if wa_key not in known_ids:
                        known_ids.add(wa_key)
                        new_entities.append(
                            AutomowerWorkAreaHeightEntity(
                                coordinator, device, wa.work_area_id
                            )
                        )
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()


class AutomowerCuttingHeightEntity(AutomowerEntity, NumberEntity):
    """Global cutting height control (1-9)."""

    _attr_translation_key = "automower_cutting_height"
    _attr_native_min_value = 1
    _attr_native_max_value = 9
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self, coordinator: AutomowerCoordinator, device: AutomowerDevice
    ) -> None:
        """Initialize the cutting height entity."""
        super().__init__(coordinator, device, "cutting_height")

    @property
    def native_value(self) -> float | None:
        """Return the current cutting height."""
        device = self._device
        if device is None:
            return None
        return float(device.settings.cutting_height)

    async def async_set_native_value(self, value: float) -> None:
        """Set the cutting height."""
        device = self._device
        if device is None:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="device_unavailable",
            )
        self.coordinator.check_command_throttle()
        try:
            await self.coordinator.client.async_set_cutting_height(
                device.mower_id, int(value)
            )
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


class AutomowerWorkAreaHeightEntity(AutomowerEntity, NumberEntity):
    """Per-work-area cutting height control (0-100%)."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = "%"

    def __init__(
        self,
        coordinator: AutomowerCoordinator,
        device: AutomowerDevice,
        work_area_id: int,
    ) -> None:
        """Initialize the work area cutting height entity."""
        super().__init__(
            coordinator, device, f"wa_{work_area_id}_height"
        )
        self._work_area_id = work_area_id
        wa = device.work_areas.get(work_area_id)
        wa_name = wa.name if wa else f"Work area {work_area_id}"
        self._attr_translation_key = "automower_work_area_cutting_height"
        self._attr_translation_placeholders = {"work_area": wa_name}

    @property
    def native_value(self) -> float | None:
        """Return the current work area cutting height."""
        device = self._device
        if device is None:
            return None
        wa = device.work_areas.get(self._work_area_id)
        if wa is None:
            return None
        return float(wa.cutting_height)

    async def async_set_native_value(self, value: float) -> None:
        """Set the work area cutting height."""
        device = self._device
        if device is None:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="device_unavailable",
            )
        self.coordinator.check_command_throttle()
        try:
            await self.coordinator.client.async_set_work_area_cutting_height(
                device.mower_id, self._work_area_id, int(value)
            )
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
