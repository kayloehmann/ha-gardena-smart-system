"""Event platform for Gardena Smart System devices."""

from __future__ import annotations

from aiogardenasmart.const import (
    MowerActivity,
    PowerSocketActivity,
    ServiceState,
    ValveActivity,
)
from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from aiogardenasmart import Device

from . import GardenaConfigEntry
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE
from .coordinator import GardenaCoordinator
from .entity import GardenaEntity

PARALLEL_UPDATES = 0

_MOWER_CUTTING_ACTIVITIES = frozenset(
    {
        MowerActivity.OK_CUTTING,
        MowerActivity.OK_CUTTING_TIMER_OVERRIDDEN,
    }
)
_MOWER_PARKED_ACTIVITIES = frozenset(
    {
        MowerActivity.PARKED_TIMER,
        MowerActivity.PARKED_PARK_SELECTED,
        MowerActivity.PARKED_AUTOTIMER,
        MowerActivity.PARKED_FROST,
    }
)
_ERROR_STATES = frozenset({ServiceState.WARNING, ServiceState.ERROR})

_MOWER_EVENT_TYPES = [
    "started_cutting",
    "stopped",
    "leaving",
    "searching",
    "charging",
    "parked",
    "paused",
    "error",
    "error_cleared",
]

_VALVE_EVENT_TYPES = [
    "started_watering",
    "stopped_watering",
    "error",
    "error_cleared",
]

_POWER_SOCKET_EVENT_TYPES = [
    "turned_on",
    "turned_off",
    "error",
    "error_cleared",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gardena event entities from a config entry."""
    if entry.data.get(CONF_API_TYPE) == API_TYPE_AUTOMOWER:
        return

    coordinator: GardenaCoordinator = entry.runtime_data
    known_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        if coordinator.data is None:
            return
        new_entities: list[EventEntity] = []
        for device in coordinator.data.values():
            if device.mower is not None:
                key = f"{device.device_id}_mower_event"
                if key not in known_ids:
                    known_ids.add(key)
                    new_entities.append(GardenaMowerEventEntity(coordinator, device))

            for service_id in device.valves:
                key = f"{device.device_id}_valve_{service_id}_event"
                if key not in known_ids:
                    known_ids.add(key)
                    new_entities.append(GardenaValveEventEntity(coordinator, device, service_id))

            if device.power_socket is not None:
                key = f"{device.device_id}_power_socket_event"
                if key not in known_ids:
                    known_ids.add(key)
                    new_entities.append(GardenaPowerSocketEventEntity(coordinator, device))

        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()


class GardenaMowerEventEntity(GardenaEntity, EventEntity):
    """Fires events on Gardena mower state transitions."""


    _attr_event_types = _MOWER_EVENT_TYPES
    _attr_translation_key = "gardena_mower_event"

    def __init__(self, coordinator: GardenaCoordinator, device: Device) -> None:
        """Initialize the mower event entity."""
        super().__init__(coordinator, device, "mower_event")
        self._prev_activity = device.mower.activity if device.mower else None
        self._prev_state = device.mower.state if device.mower else None
        self._prev_error = (device.mower.state in _ERROR_STATES) if device.mower else False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Detect mower state transitions and fire events."""
        device = self._device
        if device is None or device.mower is None:
            super()._handle_coordinator_update()
            return

        activity = device.mower.activity
        state = device.mower.state
        is_error = state in _ERROR_STATES
        event_type: str | None = None
        event_data: dict[str, str] = {}

        if is_error and not self._prev_error:
            event_type = "error"
            event_data = {"state": state or "", "activity": activity or ""}
        elif not is_error and self._prev_error:
            event_type = "error_cleared"
            event_data = {"state": state or "", "activity": activity or ""}
        elif activity != self._prev_activity and not is_error:
            if activity in _MOWER_CUTTING_ACTIVITIES:
                event_type = "started_cutting"
            elif activity == MowerActivity.OK_LEAVING:
                event_type = "leaving"
            elif activity == MowerActivity.OK_SEARCHING:
                event_type = "searching"
            elif activity == MowerActivity.OK_CHARGING:
                event_type = "charging"
            elif activity in _MOWER_PARKED_ACTIVITIES:
                event_type = "parked"
            elif activity in (MowerActivity.PAUSED, MowerActivity.PAUSED_IN_CS):
                event_type = "paused"
            elif activity == MowerActivity.STOPPED_IN_GARDEN:
                event_type = "stopped"
            if event_type:
                event_data = {"activity": activity or "", "state": state or ""}

        self._prev_activity = activity
        self._prev_state = state
        self._prev_error = is_error

        if event_type is not None:
            self._trigger_event(event_type, event_data)
        super()._handle_coordinator_update()


class GardenaValveEventEntity(GardenaEntity, EventEntity):
    """Fires events on Gardena valve state transitions."""


    _attr_event_types = _VALVE_EVENT_TYPES
    _attr_translation_key = "gardena_valve_event"

    def __init__(self, coordinator: GardenaCoordinator, device: Device, service_id: str) -> None:
        """Initialize the valve event entity."""
        suffix = (
            "valve_" + service_id.split(":")[-1] + "_event" if ":" in service_id else "valve_event"
        )
        super().__init__(coordinator, device, suffix)
        self._service_id = service_id
        valve = device.valves.get(service_id)
        self._prev_activity = valve.activity if valve else None
        self._prev_state = valve.state if valve else None
        self._prev_error = (valve.state in _ERROR_STATES) if valve else False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Detect valve state transitions and fire events."""
        device = self._device
        if device is None:
            super()._handle_coordinator_update()
            return
        valve = device.valves.get(self._service_id)
        if valve is None:
            super()._handle_coordinator_update()
            return

        activity = valve.activity
        state = valve.state
        is_error = state in _ERROR_STATES
        event_type: str | None = None
        event_data: dict[str, str] = {}

        if is_error and not self._prev_error:
            event_type = "error"
            event_data = {"state": state or ""}
        elif not is_error and self._prev_error:
            event_type = "error_cleared"
            event_data = {"state": state or ""}
        elif activity != self._prev_activity and not is_error:
            if activity in (
                ValveActivity.MANUAL_WATERING,
                ValveActivity.SCHEDULED_WATERING,
            ):
                event_type = "started_watering"
            elif activity == ValveActivity.CLOSED:
                event_type = "stopped_watering"
            if event_type:
                event_data = {"activity": activity or ""}

        self._prev_activity = activity
        self._prev_state = state
        self._prev_error = is_error

        if event_type is not None:
            self._trigger_event(event_type, event_data)
        super()._handle_coordinator_update()


class GardenaPowerSocketEventEntity(GardenaEntity, EventEntity):
    """Fires events on Gardena power socket state transitions."""


    _attr_event_types = _POWER_SOCKET_EVENT_TYPES
    _attr_translation_key = "gardena_power_socket_event"

    def __init__(self, coordinator: GardenaCoordinator, device: Device) -> None:
        """Initialize the power socket event entity."""
        super().__init__(coordinator, device, "power_socket_event")
        ps = device.power_socket
        self._prev_activity = ps.activity if ps else None
        self._prev_state = ps.state if ps else None
        self._prev_error = (ps.state in _ERROR_STATES) if ps else False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Detect power socket state transitions and fire events."""
        device = self._device
        if device is None or device.power_socket is None:
            super()._handle_coordinator_update()
            return

        ps = device.power_socket
        activity = ps.activity
        state = ps.state
        is_error = state in _ERROR_STATES
        event_type: str | None = None
        event_data: dict[str, str] = {}

        if is_error and not self._prev_error:
            event_type = "error"
            event_data = {"state": state or ""}
        elif not is_error and self._prev_error:
            event_type = "error_cleared"
            event_data = {"state": state or ""}
        elif activity != self._prev_activity and not is_error:
            if activity in (
                PowerSocketActivity.FOREVER_ON,
                PowerSocketActivity.TIME_LIMITED_ON,
                PowerSocketActivity.SCHEDULED_ON,
            ):
                event_type = "turned_on"
            elif activity == PowerSocketActivity.OFF:
                event_type = "turned_off"
            if event_type:
                event_data = {"activity": activity or ""}

        self._prev_activity = activity
        self._prev_state = state
        self._prev_error = is_error

        if event_type is not None:
            self._trigger_event(event_type, event_data)
        super()._handle_coordinator_update()
