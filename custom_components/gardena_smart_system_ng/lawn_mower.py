"""Lawn mower platform for the Gardena Smart System integration.

Maps the MOWER service to a HA lawn_mower entity.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import voluptuous as vol
from aiogardenasmart.const import ControlType, MowerActivity, ServiceState
from homeassistant.components.lawn_mower import LawnMowerEntity
from homeassistant.components.lawn_mower.const import (
    LawnMowerActivity,
    LawnMowerEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)

from aiogardenasmart import Device

from . import GardenaConfigEntry
from .const import (
    API_TYPE_AUTOMOWER,
    CONF_API_TYPE,
    DEFAULT_START_MOWING_DURATION_MINUTES,
    OPT_START_MOWING_DURATION_MINUTES,
)
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

# Expected mower activities per command kind, for the issue #22 poll-after-
# timeout recovery. Listed liberally — any of these proves the command landed.
_MOWING_ACTIVITIES = frozenset(
    {
        MowerActivity.OK_CUTTING,
        MowerActivity.OK_CUTTING_TIMER_OVERRIDDEN,
        MowerActivity.OK_LEAVING,
        MowerActivity.OK_SEARCHING,
    }
)
_PARKED_ACTIVITIES = frozenset(
    {
        MowerActivity.PARKED_PARK_SELECTED,
        MowerActivity.PARKED_TIMER,
        MowerActivity.PARKED_AUTOTIMER,
        MowerActivity.OK_CHARGING,
    }
)


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

    coordinator = cast(GardenaCoordinator, entry.runtime_data)
    known_device_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        if not coordinator.data:
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
        """Start mowing now for the configured default duration.

        Sends ``START_SECONDS_TO_OVERRIDE`` so the Lovelace "Start" button (and
        HA scheduler integrations) actually start the mower immediately, even
        when the Gardena-side schedule is empty or in a "do-not-mow" window.
        Users who explicitly want the original "resume the configured schedule"
        behaviour can use the ``gardena_smart_system_ng.resume_schedule``
        service, which still maps to ``START_DONT_OVERRIDE``.
        """
        duration_minutes: int = int(
            self.coordinator.config_entry.options.get(
                OPT_START_MOWING_DURATION_MINUTES, DEFAULT_START_MOWING_DURATION_MINUTES
            )
        )
        await self._async_send_command(
            "START_SECONDS_TO_OVERRIDE",
            expected="mowing",
            seconds=duration_minutes * 60,
        )

    async def async_override_schedule(self, duration: int) -> None:
        """Force mowing for the given number of minutes, overriding the schedule."""
        await self._async_send_command(
            "START_SECONDS_TO_OVERRIDE",
            expected="mowing",
            seconds=duration * 60,
        )

    async def async_dock(self) -> None:
        """Send the mower back to dock."""
        await self._async_send_command("PARK_UNTIL_NEXT_TASK", expected="parked")

    async def async_pause(self) -> None:
        """Pause the mower and park until further notice."""
        await self._async_send_command("PARK_UNTIL_FURTHER_NOTICE", expected="parked")

    async def async_park_until_further_notice(self) -> None:
        """Park the mower indefinitely until manually resumed."""
        await self._async_send_command("PARK_UNTIL_FURTHER_NOTICE", expected="parked")

    async def async_resume_schedule(self) -> None:
        """Resume the mower's automatic mowing schedule."""
        await self._async_send_command("START_DONT_OVERRIDE", expected="mowing")

    def _make_expected_state_check(self, expected: str | None) -> Callable[[], bool] | None:
        """Build a coordinator-state probe for issue #22 timeout recovery."""
        if expected is None:
            return None
        if expected == "mowing":
            target = _MOWING_ACTIVITIES
        elif expected == "parked":
            target = _PARKED_ACTIVITIES
        else:  # pragma: no cover — defensive
            return None

        device_id = self._device_id

        def _check() -> bool:
            data = self.coordinator.data or {}
            device = data.get(device_id)
            if device is None or device.mower is None:
                return False
            return device.mower.activity in target

        return _check

    async def _async_send_command(
        self, command: str, *, expected: str | None = None, **params: int
    ) -> None:
        """Send a command to the mower service."""
        device = self._device
        if device is None or device.mower is None:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system_ng",
                translation_key="device_unavailable",
            )
        await self._async_execute_command(
            self.coordinator.async_send_command,
            service_id=device.mower.service_id,
            control_type=ControlType.MOWER,
            command=command,
            expected_state_check=self._make_expected_state_check(expected),
            **params,
        )
