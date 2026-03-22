"""Lawn mower platform for Automower devices."""

from __future__ import annotations

from typing import Any

from aioautomower import AutomowerDevice
from aioautomower.const import MowerActivity, MowerState
from aioautomower.exceptions import AutomowerAuthenticationError, AutomowerException

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

from . import GardenaConfigEntry
from .automower_coordinator import AutomowerCoordinator
from .automower_entity import AutomowerEntity
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE, DOMAIN

PARALLEL_UPDATES = 1

SERVICE_PARK_UNTIL_FURTHER_NOTICE = "park_until_further_notice"
SERVICE_RESUME_SCHEDULE = "resume_schedule"

_ACTIVITY_MAP: dict[str, LawnMowerActivity] = {
    MowerActivity.MOWING: LawnMowerActivity.MOWING,
    MowerActivity.LEAVING: LawnMowerActivity.MOWING,
    MowerActivity.GOING_HOME: LawnMowerActivity.MOWING,
    MowerActivity.CHARGING: LawnMowerActivity.DOCKED,
    MowerActivity.PARKED_IN_CS: LawnMowerActivity.DOCKED,
    MowerActivity.STOPPED_IN_GARDEN: LawnMowerActivity.ERROR,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Automower lawn mower entities from a config entry."""
    if entry.data.get(CONF_API_TYPE) != API_TYPE_AUTOMOWER:
        return

    coordinator: AutomowerCoordinator = entry.runtime_data
    known_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        new_entities: list[AutomowerLawnMowerEntity] = []
        for device in coordinator.data.values():
            if device.mower_id not in known_ids:
                known_ids.add(device.mower_id)
                new_entities.append(
                    AutomowerLawnMowerEntity(coordinator, device)
                )
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()

    platform = async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_PARK_UNTIL_FURTHER_NOTICE,
        {},
        "async_park_until_further_notice",
    )
    platform.async_register_entity_service(
        SERVICE_RESUME_SCHEDULE,
        {},
        "async_resume_schedule",
    )


class AutomowerLawnMowerEntity(AutomowerEntity, LawnMowerEntity):
    """Represents a Husqvarna Automower robotic lawn mower."""

    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING
        | LawnMowerEntityFeature.DOCK
        | LawnMowerEntityFeature.PAUSE
    )
    _attr_translation_key = "automower"

    def __init__(
        self, coordinator: AutomowerCoordinator, device: AutomowerDevice
    ) -> None:
        """Initialize the lawn mower entity."""
        super().__init__(coordinator, device, "automower")

    @property
    def activity(self) -> LawnMowerActivity | None:
        """Return the current mower activity."""
        device = self._device
        if device is None:
            return None
        if device.mower.state in (MowerState.ERROR, MowerState.FATAL_ERROR):
            return LawnMowerActivity.ERROR
        if device.mower.state == MowerState.PAUSED:
            return LawnMowerActivity.PAUSED
        return _ACTIVITY_MAP.get(device.mower.activity, LawnMowerActivity.DOCKED)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose detailed Automower API fields for frontend cards."""
        device = self._device
        if device is None:
            return None
        attrs: dict[str, Any] = {
            "activity": device.mower.activity,
            "state": device.mower.state,
            "mode": device.mower.mode,
        }
        if device.mower.error_code != 0:
            attrs["error_code"] = device.mower.error_code
        if device.planner.restricted_reason != "NONE":
            attrs["restricted_reason"] = device.planner.restricted_reason
        if device.planner.override.action != "NOT_ACTIVE":
            attrs["override_action"] = device.planner.override.action
        return attrs

    async def async_start_mowing(self) -> None:
        """Start mowing (resume schedule)."""
        await self._async_send_command("start")

    async def async_dock(self) -> None:
        """Send the mower back to dock until next schedule."""
        await self._async_send_command("park_until_next_schedule")

    async def async_pause(self) -> None:
        """Pause the mower."""
        await self._async_send_command("pause")

    async def async_park_until_further_notice(self) -> None:
        """Park the mower indefinitely until manually resumed."""
        await self._async_send_command("park_until_further_notice")

    async def async_resume_schedule(self) -> None:
        """Resume the mower's automatic schedule."""
        await self._async_send_command("resume_schedule")

    async def _async_send_command(self, command: str, **kwargs: Any) -> None:
        """Send a command to the Automower API."""
        device = self._device
        if device is None:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="device_unavailable",
            )
        self.coordinator.check_command_throttle()
        try:
            client = self.coordinator.client
            if command == "start":
                await client.async_start(device.mower_id, **kwargs)
            elif command == "pause":
                await client.async_pause(device.mower_id)
            elif command == "park_until_next_schedule":
                await client.async_park_until_next_schedule(device.mower_id)
            elif command == "park_until_further_notice":
                await client.async_park_until_further_notice(device.mower_id)
            elif command == "resume_schedule":
                await client.async_resume_schedule(device.mower_id)
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
