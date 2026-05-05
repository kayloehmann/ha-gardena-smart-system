"""Valve platform for the Gardena Smart System integration.

Maps each Gardena VALVE service (irrigation zone or standalone water control)
to a HA valve entity.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

import voluptuous as vol
from aiogardenasmart.const import ControlType, ValveActivity
from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform as ep
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from aiogardenasmart import Device, ValveService

from . import GardenaConfigEntry
from .const import DEFAULT_WATERING_MINUTES, OPT_DEFAULT_WATERING_MINUTES
from .coordinator import GardenaCoordinator
from .entity import GardenaEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

MAX_WATERING_DURATION_MINUTES = 1440  # 24 hours

# Smart Irrigation Control allows at most this many valves open simultaneously
# per controller. Opening a third is rejected by the Husqvarna API.
MAX_CONCURRENT_IRRIGATION_VALVES = 2


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
        if not coordinator.data:
            return
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
        duration_minutes: int = int(
            self.coordinator.config_entry.options.get(
                OPT_DEFAULT_WATERING_MINUTES, DEFAULT_WATERING_MINUTES
            )
        )
        self._check_concurrent_valve_limit()
        await self._async_send_command(
            "START_SECONDS_TO_OVERRIDE",
            seconds=duration_minutes * 60,
        )

    async def async_start_watering(self, duration: int) -> None:
        """Start watering for the given number of minutes."""
        self._check_concurrent_valve_limit()
        await self._async_send_command(
            "START_SECONDS_TO_OVERRIDE",
            seconds=duration * 60,
        )

    async def async_close_valve(self, **kwargs: Any) -> None:
        """Close the valve immediately."""
        await self._async_send_command("STOP_UNTIL_NEXT_TASK")

    def _check_concurrent_valve_limit(self) -> None:
        """Refuse opening if the irrigation controller's concurrent limit is reached.

        Applies only to valves that belong to a Smart Irrigation Control
        (device with a VALVE_SET service). Standalone Water Controls have no
        such limit.
        """
        device = self._device
        if device is None or device.valve_set is None:
            return
        already_open = sum(
            1
            for sid, valve in device.valves.items()
            if sid != self._service_id and valve.activity != ValveActivity.CLOSED
        )
        if already_open >= MAX_CONCURRENT_IRRIGATION_VALVES:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="too_many_open_valves",
                translation_placeholders={"limit": str(MAX_CONCURRENT_IRRIGATION_VALVES)},
            )

    def _make_expected_state_check(self, command: str) -> Callable[[], bool] | None:
        """Build a coordinator-state probe for issue #22 timeout recovery."""
        if command == "START_SECONDS_TO_OVERRIDE":
            target = (ValveActivity.MANUAL_WATERING, ValveActivity.SCHEDULED_WATERING)
        elif command == "STOP_UNTIL_NEXT_TASK":
            target = (ValveActivity.CLOSED,)
        else:
            return None

        device_id = self._device_id
        service_id = self._service_id

        def _check() -> bool:
            data = self.coordinator.data or {}
            device = data.get(device_id)
            if device is None:
                return False
            valve = device.valves.get(service_id)
            if valve is None:
                return False
            return valve.activity in target

        return _check

    async def _async_send_command(self, command: str, **params: int) -> None:
        """Send a command to this valve."""
        if self._device is None or self._valve is None:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="device_unavailable",
            )
        await self._async_execute_command(
            self.coordinator.client.async_send_command,
            service_id=self._service_id,
            control_type=ControlType.VALVE,
            command=command,
            expected_state_check=self._make_expected_state_check(command),
            **params,
        )
        self._apply_optimistic_state(command, params)

    def _apply_optimistic_state(self, command: str, params: dict[str, int]) -> None:
        """Apply the expected state locally after a successful command.

        The Gardena API returns 204 with no body and the confirming WebSocket
        event may take a few seconds (or, rarely, be missed entirely if the WS
        was silently dropped). Updating the local state immediately keeps the
        HA UI in sync with reality and makes the concurrent-valve preflight
        check see the newly-open valve on the next call.
        """
        valve = self._valve
        if valve is None:
            return
        if command == "START_SECONDS_TO_OVERRIDE":
            valve.activity = ValveActivity.MANUAL_WATERING
            seconds = params.get("seconds")
            if isinstance(seconds, int):
                valve.duration = seconds
                valve.duration_timestamp = datetime.now(tz=UTC).isoformat()
        elif command == "STOP_UNTIL_NEXT_TASK":
            valve.activity = ValveActivity.CLOSED
            valve.duration = 0
            valve.duration_timestamp = None
        else:
            return
        # Push the mutation through the coordinator so all listeners (this
        # entity, sibling valves on the same controller, countdown sensors)
        # refresh immediately.
        self.coordinator.async_set_updated_data(self.coordinator.data or {})
