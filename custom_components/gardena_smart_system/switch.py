"""Switch platform for the Gardena Smart System integration.

Maps the POWER_SOCKET service to a HA switch entity.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

import voluptuous as vol
from aiogardenasmart.const import ControlType, PowerSocketActivity
from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform as ep
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from aiogardenasmart import Device

from . import GardenaConfigEntry
from .const import (
    API_TYPE_AUTOMOWER,
    CONF_API_TYPE,
    DEFAULT_SOCKET_MINUTES,
    OPT_DEFAULT_SOCKET_MINUTES,
)
from .coordinator import GardenaCoordinator
from .entity import GardenaEntity

PARALLEL_UPDATES = 1

MAX_SOCKET_DURATION_MINUTES = 1440  # 24 hours


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gardena switch entities from a config entry."""
    if entry.data.get(CONF_API_TYPE) == API_TYPE_AUTOMOWER:
        from .automower_switch import async_setup_entry as automower_setup

        await automower_setup(hass, entry, async_add_entities)
        return

    coordinator = cast(GardenaCoordinator, entry.runtime_data)
    known_device_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        if not coordinator.data:
            return
        new_entities: list[GardenaPowerSocketEntity] = []
        for device in coordinator.data.values():
            if device.power_socket is not None and device.device_id not in known_device_ids:
                known_device_ids.add(device.device_id)
                new_entities.append(GardenaPowerSocketEntity(coordinator, device))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()

    platform = ep.async_get_current_platform()
    platform.async_register_entity_service(
        "turn_on_for",
        {
            vol.Required("duration"): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=MAX_SOCKET_DURATION_MINUTES)
            )
        },
        "async_turn_on_for",
    )


class GardenaPowerSocketEntity(GardenaEntity, SwitchEntity):
    """Represents a Gardena Smart Power Outlet."""

    _attr_device_class = SwitchDeviceClass.OUTLET
    _attr_translation_key = "power_socket"

    def __init__(self, coordinator: GardenaCoordinator, device: Device) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, device, "power_socket")

    @property
    def is_on(self) -> bool | None:
        """Return True if the socket is on."""
        device = self._device
        if device is None or device.power_socket is None:
            return None
        return device.power_socket.activity in (
            PowerSocketActivity.FOREVER_ON,
            PowerSocketActivity.TIME_LIMITED_ON,
            PowerSocketActivity.SCHEDULED_ON,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the socket on for the configured default duration."""
        duration_minutes: int = int(
            self.coordinator.config_entry.options.get(
                OPT_DEFAULT_SOCKET_MINUTES, DEFAULT_SOCKET_MINUTES
            )
        )
        await self._async_send_command(
            "START_SECONDS_TO_OVERRIDE",
            seconds=duration_minutes * 60,
        )

    async def async_turn_on_for(self, duration: int) -> None:
        """Turn the socket on for the given number of minutes."""
        await self._async_send_command(
            "START_SECONDS_TO_OVERRIDE",
            seconds=duration * 60,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the socket off."""
        await self._async_send_command("STOP_UNTIL_NEXT_TASK")

    def _make_expected_state_check(self, command: str) -> Callable[[], bool] | None:
        """Build a coordinator-state probe for issue #22 timeout recovery."""
        if command == "START_SECONDS_TO_OVERRIDE":
            target = (
                PowerSocketActivity.TIME_LIMITED_ON,
                PowerSocketActivity.FOREVER_ON,
                PowerSocketActivity.SCHEDULED_ON,
            )
        elif command == "STOP_UNTIL_NEXT_TASK":
            target = (PowerSocketActivity.OFF,)
        else:
            return None

        device_id = self._device_id

        def _check() -> bool:
            data = self.coordinator.data or {}
            device = data.get(device_id)
            if device is None or device.power_socket is None:
                return False
            return device.power_socket.activity in target

        return _check

    async def _async_send_command(self, command: str, **params: int) -> None:
        """Send a command to the power socket service."""
        device = self._device
        if device is None or device.power_socket is None:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="device_unavailable",
            )
        await self._async_execute_command(
            self.coordinator.client.async_send_command,
            service_id=device.power_socket.service_id,
            control_type=ControlType.POWER_SOCKET,
            command=command,
            expected_state_check=self._make_expected_state_check(command),
            **params,
        )
        self._apply_optimistic_state(command, params)

    def _apply_optimistic_state(self, command: str, params: dict[str, int]) -> None:
        """Apply the expected state locally after a successful command.

        The Gardena API returns 204 with no body and the confirming WebSocket
        event may take a few seconds or, rarely, be missed entirely. Updating
        the local state immediately keeps the HA UI in sync with reality and
        removes the need for assumed_state (which HA renders as two separate
        on/off buttons instead of a single toggle).
        """
        device = self._device
        if device is None or device.power_socket is None:
            return
        ps = device.power_socket
        if command == "START_SECONDS_TO_OVERRIDE":
            ps.activity = PowerSocketActivity.TIME_LIMITED_ON
            seconds = params.get("seconds")
            if isinstance(seconds, int):
                ps.duration = seconds
                ps.duration_timestamp = datetime.now(tz=UTC).isoformat()
        elif command == "STOP_UNTIL_NEXT_TASK":
            ps.activity = PowerSocketActivity.OFF
            ps.duration = 0
            ps.duration_timestamp = None
        else:
            return
        self.coordinator.async_set_updated_data(self.coordinator.data or {})
