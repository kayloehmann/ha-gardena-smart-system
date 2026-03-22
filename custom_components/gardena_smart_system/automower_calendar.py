"""Calendar platform for Automower mowing schedule."""

from __future__ import annotations

from datetime import datetime, timedelta

from aioautomower import AutomowerDevice, ScheduleTask

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import GardenaConfigEntry
from .automower_coordinator import AutomowerCoordinator
from .automower_entity import AutomowerEntity
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE

PARALLEL_UPDATES = 0

_WEEKDAY_MAP = {
    0: "monday",
    1: "tuesday",
    2: "wednesday",
    3: "thursday",
    4: "friday",
    5: "saturday",
    6: "sunday",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Automower calendar entities."""
    if entry.data.get(CONF_API_TYPE) != API_TYPE_AUTOMOWER:
        return

    coordinator: AutomowerCoordinator = entry.runtime_data
    known_ids: set[str] = set()

    @callback
    def _async_add_new_entities() -> None:
        new_entities: list[AutomowerCalendarEntity] = []
        for device in coordinator.data.values():
            if device.mower_id not in known_ids:
                known_ids.add(device.mower_id)
                new_entities.append(
                    AutomowerCalendarEntity(coordinator, device)
                )
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()


class AutomowerCalendarEntity(AutomowerEntity, CalendarEntity):
    """Calendar showing the mowing schedule (read-only)."""

    _attr_translation_key = "automower_schedule"

    def __init__(
        self, coordinator: AutomowerCoordinator, device: AutomowerDevice
    ) -> None:
        """Initialize the calendar entity."""
        super().__init__(coordinator, device, "schedule")

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming mowing event."""
        device = self._device
        if device is None:
            return None

        now = dt_util.now()
        events = self._generate_events(device, now, now + timedelta(days=7))
        upcoming = [e for e in events if e.end > now]
        if not upcoming:
            return None
        return min(upcoming, key=lambda e: e.start)

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events in a date range."""
        device = self._device
        if device is None:
            return []
        return self._generate_events(device, start_date, end_date)

    @staticmethod
    def _generate_events(
        device: AutomowerDevice,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Generate calendar events from the mower's schedule tasks."""
        events: list[CalendarEvent] = []
        if not device.calendar.tasks:
            return events

        current = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        while current.date() <= end_date.date():
            weekday = current.weekday()
            weekday_attr = _WEEKDAY_MAP[weekday]

            for task in device.calendar.tasks:
                if not getattr(task, weekday_attr, False):
                    continue

                task_start = current + timedelta(minutes=task.start)
                task_end = task_start + timedelta(minutes=task.duration)

                if task_end < start_date or task_start > end_date:
                    continue

                work_area_name = ""
                description_parts: list[str] = []
                if task.work_area_id is not None:
                    wa = device.work_areas.get(task.work_area_id)
                    if wa:
                        work_area_name = f" ({wa.name})"
                        if wa.cutting_height is not None:
                            description_parts.append(
                                f"Cutting height: {wa.cutting_height}%"
                            )

                if device.settings.cutting_height is not None:
                    description_parts.append(
                        f"Global cutting height: {device.settings.cutting_height}"
                    )

                events.append(
                    CalendarEvent(
                        start=task_start,
                        end=task_end,
                        summary=f"Mowing{work_area_name}",
                        description="\n".join(description_parts)
                        if description_parts
                        else None,
                    )
                )

            current += timedelta(days=1)

        return events
