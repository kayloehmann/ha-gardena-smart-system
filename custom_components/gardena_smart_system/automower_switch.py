"""Switch platform for Automower headlights and zones."""

from __future__ import annotations

from typing import Any

from aioautomower import AutomowerDevice
from aioautomower.const import HeadlightMode
from aioautomower.exceptions import AutomowerAuthenticationError, AutomowerException

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
    """Set up Automower switch entities."""
    if entry.data.get(CONF_API_TYPE) != API_TYPE_AUTOMOWER:
        return

    coordinator: AutomowerCoordinator = entry.runtime_data
    known_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        new_entities: list[SwitchEntity] = []
        for device in coordinator.data.values():
            # Headlight switch
            if device.capabilities.headlights:
                key = f"{device.mower_id}_headlight"
                if key not in known_ids:
                    known_ids.add(key)
                    new_entities.append(
                        AutomowerHeadlightSwitch(coordinator, device)
                    )

            # Stay-out zone switches
            if device.capabilities.stay_out_zones:
                for zone in device.stay_out_zones.values():
                    key = f"{device.mower_id}_soz_{zone.zone_id}"
                    if key not in known_ids:
                        known_ids.add(key)
                        new_entities.append(
                            AutomowerStayOutZoneSwitch(
                                coordinator, device, zone.zone_id
                            )
                        )

        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()


class AutomowerHeadlightSwitch(AutomowerEntity, SwitchEntity):
    """Headlight on/off switch."""

    _attr_translation_key = "automower_headlight"

    def __init__(
        self, coordinator: AutomowerCoordinator, device: AutomowerDevice
    ) -> None:
        """Initialize the headlight switch."""
        super().__init__(coordinator, device, "headlight")

    @property
    def is_on(self) -> bool | None:
        """Return True if headlights are on."""
        device = self._device
        if device is None:
            return None
        return device.settings.headlight_mode != HeadlightMode.ALWAYS_OFF

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn headlights on."""
        await self._async_set_headlight(HeadlightMode.ALWAYS_ON)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn headlights off."""
        await self._async_set_headlight(HeadlightMode.ALWAYS_OFF)

    async def _async_set_headlight(self, mode: str) -> None:
        device = self._device
        if device is None:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="device_unavailable",
            )
        self.coordinator.check_command_throttle()
        try:
            await self.coordinator.client.async_set_headlight_mode(
                device.mower_id, mode
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


class AutomowerStayOutZoneSwitch(AutomowerEntity, SwitchEntity):
    """Enable/disable a stay-out zone."""

    _attr_translation_key = "automower_stay_out_zone"

    def __init__(
        self,
        coordinator: AutomowerCoordinator,
        device: AutomowerDevice,
        zone_id: str,
    ) -> None:
        """Initialize the stay-out zone switch."""
        super().__init__(coordinator, device, f"soz_{zone_id}")
        self._zone_id = zone_id
        zone = device.stay_out_zones.get(zone_id)
        zone_name = zone.name if zone else zone_id
        self._attr_translation_placeholders = {"zone_name": zone_name}

    @property
    def is_on(self) -> bool | None:
        """Return True if the stay-out zone is enabled."""
        device = self._device
        if device is None:
            return None
        zone = device.stay_out_zones.get(self._zone_id)
        if zone is None:
            return None
        return zone.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the stay-out zone."""
        await self._async_set_zone(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the stay-out zone."""
        await self._async_set_zone(False)

    async def _async_set_zone(self, enabled: bool) -> None:
        device = self._device
        if device is None:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="device_unavailable",
            )
        self.coordinator.check_command_throttle()
        try:
            await self.coordinator.client.async_set_stay_out_zone(
                device.mower_id, self._zone_id, enabled
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
