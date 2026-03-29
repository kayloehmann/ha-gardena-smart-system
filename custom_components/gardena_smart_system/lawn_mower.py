"""Lawn mower platform for the Gardena Smart System integration.

Maps the MOWER service to a HA lawn_mower entity.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from aiogardenasmart.const import ControlType, MowerActivity, ServiceState
from homeassistant.components.lawn_mower import LawnMowerEntity
from homeassistant.components.lawn_mower.const import (
    LawnMowerActivity,
    LawnMowerEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)

from aiogardenasmart import Device, GardenaAuthenticationError, GardenaException

from . import GardenaConfigEntry
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE
from .coordinator import GardenaCoordinator
from .entity import GardenaEntity

PARALLEL_UPDATES = 1

MAX_MOWING_DURATION_MINUTES = 480  # 8 hours

_MOWER_ACTIVITY_MAP: dict[str, LawnMowerActivity] = {
    MowerActivity.OK_CUTTING: LawnMowerActivity.MOWING,
    MowerActivity.OK_CUTTING_TIMER_OVERRIDDEN: LawnMowerActivity.MOWING,
    MowerActivity.OK_SEARCHING: LawnMowerActivity.MOWING,
    MowerActivity.OK_LEAVING: LawnMowerActivity.MOWING,
    MowerActivity.OK_CHARGING: LawnMowerActivity.DOCKED,
    MowerActivity.PARKED_TIMER: LawnMowerActivity.DOCKED,
    MowerActivity.PARKED_PARK_SELECTED: LawnMowerActivity.DOCKED,
    MowerActivity.PARKED_AUTOTIMER: LawnMowerActivity.DOCKED,
    MowerActivity.PARKED_FROST: LawnMowerActivity.DOCKED,
    MowerActivity.PAUSED: LawnMowerActivity.PAUSED,
    MowerActivity.PAUSED_IN_CS: LawnMowerActivity.PAUSED,
    MowerActivity.STOPPED_IN_GARDEN: LawnMowerActivity.ERROR,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gardena lawn mower entities from a config entry."""
    if entry.data.get(CONF_API_TYPE) == API_TYPE_AUTOMOWER:
        from .automower_lawn_mower import async_setup_entry as automower_setup

        await automower_setup(hass, entry, async_add_entities)
        return

    coordinator = entry.runtime_data
    known_device_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        if coordinator.data is None:
            return
        new_entities: list[GardenaLawnMowerEntity] = []
        for device in coordinator.data.values():
            if device.mower is not None and device.device_id not in known_device_ids:
                known_device_ids.add(device.device_id)
                new_entities.append(GardenaLawnMowerEntity(coordinator, device))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()

    platform = async_get_current_platform()
    platform.async_register_entity_service(
        "override_schedule",
        {
            vol.Required("duration"): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=MAX_MOWING_DURATION_MINUTES)
            )
        },
        "async_override_schedule",
    )
    platform.async_register_entity_service(
        "park_until_further_notice",
        {},
        "async_park_until_further_notice",
    )
    platform.async_register_entity_service(
        "resume_schedule",
        {},
        "async_resume_schedule",
    )


class GardenaLawnMowerEntity(GardenaEntity, LawnMowerEntity):
    """Represents a Gardena SILENO robotic lawn mower."""

    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING
        | LawnMowerEntityFeature.DOCK
        | LawnMowerEntityFeature.PAUSE
    )
    _attr_translation_key = "mower"
    _attr_assumed_state = True

    def __init__(self, coordinator: GardenaCoordinator, device: Device) -> None:
        """Initialize the lawn mower entity."""
        super().__init__(coordinator, device, "mower")

    @property
    def activity(self) -> LawnMowerActivity | None:
        """Return the current mower activity."""
        device = self._device
        if device is None or device.mower is None:
            return None
        if device.mower.state == ServiceState.ERROR:
            return LawnMowerActivity.ERROR
        return _MOWER_ACTIVITY_MAP.get(device.mower.activity or "", LawnMowerActivity.PAUSED)

    async def async_start_mowing(self) -> None:
        """Start mowing without overriding the schedule."""
        await self._async_send_command("START_DONT_OVERRIDE")

    async def async_override_schedule(self, duration: int) -> None:
        """Force mowing for the given number of minutes, overriding the schedule."""
        await self._async_send_command(
            "START_SECONDS_TO_OVERRIDE",
            seconds=duration * 60,
        )

    async def async_dock(self) -> None:
        """Send the mower back to dock."""
        await self._async_send_command("PARK_UNTIL_NEXT_TASK")

    async def async_pause(self) -> None:
        """Pause the mower and park until further notice."""
        await self._async_send_command("PARK_UNTIL_FURTHER_NOTICE")

    async def async_park_until_further_notice(self) -> None:
        """Park the mower indefinitely until manually resumed."""
        await self._async_send_command("PARK_UNTIL_FURTHER_NOTICE")

    async def async_resume_schedule(self) -> None:
        """Resume the mower's automatic mowing schedule."""
        await self._async_send_command("START_DONT_OVERRIDE")

    async def _async_send_command(self, command: str, **params: int) -> None:
        """Send a command to the mower service."""
        device = self._device
        if device is None or device.mower is None:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="device_unavailable",
            )
        self.coordinator.check_command_throttle()
        try:
            await self.coordinator.client.async_send_command(
                service_id=device.mower.service_id,
                control_type=ControlType.MOWER,
                command=command,
                **params,
            )
        except GardenaAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain="gardena_smart_system",
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except GardenaException as err:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
