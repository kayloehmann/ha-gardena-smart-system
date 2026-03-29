"""Event platform for Automower devices."""

from __future__ import annotations

from typing import cast

from aioautomower.const import MowerActivity, MowerState
from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from aioautomower import AutomowerDevice

from . import GardenaConfigEntry
from .automower_coordinator import AutomowerCoordinator
from .automower_entity import AutomowerEntity
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE

PARALLEL_UPDATES = 0

# Event types emitted by the mower event entity
EVENT_STARTED_MOWING = "started_mowing"
EVENT_STOPPED = "stopped"
EVENT_GOING_HOME = "going_home"
EVENT_CHARGING = "charging"
EVENT_LEAVING = "leaving"
EVENT_PARKED = "parked"
EVENT_PAUSED = "paused"
EVENT_ERROR = "error"
EVENT_ERROR_CLEARED = "error_cleared"

_ALL_EVENT_TYPES: list[str] = [
    EVENT_STARTED_MOWING,
    EVENT_STOPPED,
    EVENT_GOING_HOME,
    EVENT_CHARGING,
    EVENT_LEAVING,
    EVENT_PARKED,
    EVENT_PAUSED,
    EVENT_ERROR,
    EVENT_ERROR_CLEARED,
]

_ERROR_STATES = frozenset({MowerState.ERROR, MowerState.FATAL_ERROR})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Automower event entities from a config entry."""
    if entry.data.get(CONF_API_TYPE) != API_TYPE_AUTOMOWER:
        return

    coordinator = cast(AutomowerCoordinator, entry.runtime_data)
    known_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        if coordinator.data is None:
            return  # type: ignore[unreachable]
        new_entities: list[AutomowerEventEntity] = []
        for device in coordinator.data.values():
            if device.mower_id not in known_ids:
                known_ids.add(device.mower_id)
                new_entities.append(AutomowerEventEntity(coordinator, device))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()


class AutomowerEventEntity(AutomowerEntity, EventEntity):
    """Fires events on Automower state and activity transitions."""

    _attr_event_types = _ALL_EVENT_TYPES
    _attr_translation_key = "automower_event"

    def __init__(
        self,
        coordinator: AutomowerCoordinator,
        device: AutomowerDevice,
    ) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator, device, "event")
        self._prev_activity: str | None = device.mower.activity
        self._prev_state: str | None = device.mower.state
        self._prev_error: bool = device.mower.state in _ERROR_STATES

    @callback
    def _handle_coordinator_update(self) -> None:
        """Detect state transitions and fire events."""
        device = self._device
        if device is None:
            super()._handle_coordinator_update()
            return

        activity = device.mower.activity
        state = device.mower.state
        is_error = state in _ERROR_STATES
        event_type: str | None = None
        event_data: dict[str, str] = {}

        # Error transitions take priority
        if is_error and not self._prev_error:
            event_type = EVENT_ERROR
            event_data = {
                "state": state,
                "error_code": str(device.mower.error_code),
            }
        elif not is_error and self._prev_error:
            event_type = EVENT_ERROR_CLEARED
            event_data = {"state": state, "activity": activity}
        elif activity != self._prev_activity and not is_error:
            # Activity changed — map to event
            if activity == MowerActivity.MOWING:
                event_type = EVENT_STARTED_MOWING
            elif activity == MowerActivity.GOING_HOME:
                event_type = EVENT_GOING_HOME
            elif activity == MowerActivity.CHARGING:
                event_type = EVENT_CHARGING
            elif activity == MowerActivity.LEAVING:
                event_type = EVENT_LEAVING
            elif activity == MowerActivity.PARKED_IN_CS:
                event_type = EVENT_PARKED
            elif activity == MowerActivity.STOPPED_IN_GARDEN:
                event_type = EVENT_STOPPED
            if event_type:
                event_data = {"activity": activity, "state": state}
        elif state != self._prev_state and not is_error:
            # State changed without activity change (e.g. PAUSED)
            if state == MowerState.PAUSED:
                event_type = EVENT_PAUSED
                event_data = {"activity": activity, "state": state}

        self._prev_activity = activity
        self._prev_state = state
        self._prev_error = is_error

        if event_type is not None:
            self._trigger_event(event_type, event_data)

        super()._handle_coordinator_update()
