"""Valve platform for the Gardena Smart System integration.

Maps each Gardena VALVE service (irrigation zone or standalone water control)
to a HA valve entity.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import voluptuous as vol
from aiogardenasmart.const import ControlType, ValveActivity
from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import entity_platform as ep
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from aiogardenasmart import Device, GardenaAuthenticationError, GardenaException, ValveService

from . import GardenaConfigEntry
from .const import DEFAULT_WATERING_MINUTES, OPT_DEFAULT_WATERING_MINUTES
from .coordinator import GardenaCoordinator
from .entity import GardenaEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

MAX_WATERING_DURATION_MINUTES = 1440  # 24 hours


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gardena valve entities from a config entry."""
    coordinator = cast(GardenaCoordinator, entry.runtime_data)
    known_service_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        if coordinator.data is None:
            return  # type: ignore[unreachable]
        new_entities: list[GardenaValveEntity] = []
        for device in coordinator.data.values():
            for service_id in device.valves:
                if service_id not in known_service_ids:
                    known_service_ids.add(service_id)
                    new_entities.append(GardenaValveEntity(coordinator, device, service_id))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()

    platform = ep.async_get_current_platform()
    platform.async_register_entity_service(
        "start_watering",
        {
            vol.Required("duration"): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=MAX_WATERING_DURATION_MINUTES)
            )
        },
        "async_start_watering",
    )


class GardenaValveEntity(GardenaEntity, ValveEntity):
    """Represents a single Gardena irrigation valve."""

    _attr_device_class = ValveDeviceClass.WATER
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    _attr_reports_position = False
    _attr_assumed_state = True

    def __init__(
        self,
        coordinator: GardenaCoordinator,
        device: Device,
        service_id: str,
    ) -> None:
        """Initialize the valve entity."""
        # Use the valve index from the service_id (e.g., "uuid:1" → suffix "valve_1")
        suffix = "valve_" + service_id.split(":")[-1] if ":" in service_id else "valve"
        super().__init__(coordinator, device, suffix)
        self._service_id = service_id
        valve_service = device.valves.get(service_id)
        if valve_service and valve_service.name:
            self._attr_name = valve_service.name
        else:
            self._attr_translation_key = "valve"

    @property
    def _valve(self) -> ValveService | None:
        """Return the current valve service state."""
        device = self._device
        if device is None:
            return None
        return device.valves.get(self._service_id)

    @property
    def is_closed(self) -> bool | None:
        """Return True if the valve is closed."""
        valve = self._valve
        if valve is None:
            return None
        return valve.activity == ValveActivity.CLOSED

    async def async_open_valve(self, **kwargs: Any) -> None:
        """Open the valve for the configured default duration."""
        duration_minutes: int = self.coordinator.config_entry.options.get(
            OPT_DEFAULT_WATERING_MINUTES, DEFAULT_WATERING_MINUTES
        )
        await self._async_send_command(
            "START_SECONDS_TO_OVERRIDE",
            seconds=duration_minutes * 60,
        )

    async def async_start_watering(self, duration: int) -> None:
        """Start watering for the given number of minutes."""
        await self._async_send_command(
            "START_SECONDS_TO_OVERRIDE",
            seconds=duration * 60,
        )

    async def async_close_valve(self, **kwargs: Any) -> None:
        """Close the valve immediately."""
        await self._async_send_command("STOP_UNTIL_NEXT_TASK")

    async def _async_send_command(self, command: str, **params: int) -> None:
        """Send a command to this valve."""
        if self._device is None or self._valve is None:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="device_unavailable",
            )
        self.coordinator.check_command_throttle()
        try:
            await self.coordinator.client.async_send_command(
                service_id=self._service_id,
                control_type=ControlType.VALVE,
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
