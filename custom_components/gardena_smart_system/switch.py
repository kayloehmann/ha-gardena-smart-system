"""Switch platform for the Gardena Smart System integration.

Maps the POWER_SOCKET service to a HA switch entity.
"""

from __future__ import annotations

from typing import Any, cast

import voluptuous as vol
from aiogardenasmart.const import ControlType, PowerSocketActivity
from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import entity_platform as ep
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from aiogardenasmart import Device, GardenaAuthenticationError, GardenaException

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
        if coordinator.data is None:
            return  # type: ignore[unreachable]
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
    _attr_assumed_state = True

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

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the power socket activity and remaining duration as extra attributes."""
        device = self._device
        if device is None or device.power_socket is None:
            return None
        attrs: dict[str, Any] = {"activity": device.power_socket.activity}
        if device.power_socket.duration is not None and device.power_socket.duration > 0:
            attrs["duration"] = device.power_socket.duration
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the socket on for the configured default duration."""
        duration_minutes: int = self.coordinator.config_entry.options.get(
            OPT_DEFAULT_SOCKET_MINUTES, DEFAULT_SOCKET_MINUTES
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

    async def _async_send_command(self, command: str, **params: int) -> None:
        """Send a command to the power socket service."""
        device = self._device
        if device is None or device.power_socket is None:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="device_unavailable",
            )
        self.coordinator.check_command_throttle()
        try:
            await self.coordinator.client.async_send_command(
                service_id=device.power_socket.service_id,
                control_type=ControlType.POWER_SOCKET,
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
