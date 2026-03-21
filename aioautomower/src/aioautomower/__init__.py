"""Async Python client for the Husqvarna Automower Connect API v1."""

from .client import AutomowerClient
from .exceptions import (
    AutomowerAuthenticationError,
    AutomowerConnectionError,
    AutomowerException,
    AutomowerForbiddenError,
    AutomowerRateLimitError,
    AutomowerRequestError,
    AutomowerWebSocketError,
)
from .models import (
    AutomowerDevice,
    BatteryInfo,
    CalendarInfo,
    CapabilitiesInfo,
    MetadataInfo,
    MowerInfo,
    PlannerInfo,
    Position,
    ScheduleTask,
    SettingsInfo,
    StatisticsInfo,
    StayOutZone,
    SystemInfo,
    WorkArea,
)
from .websocket import AutomowerWebSocket

__all__ = [
    "AutomowerClient",
    "AutomowerDevice",
    "AutomowerException",
    "AutomowerAuthenticationError",
    "AutomowerConnectionError",
    "AutomowerForbiddenError",
    "AutomowerRateLimitError",
    "AutomowerRequestError",
    "AutomowerWebSocketError",
    "AutomowerWebSocket",
    "BatteryInfo",
    "CalendarInfo",
    "CapabilitiesInfo",
    "MetadataInfo",
    "MowerInfo",
    "PlannerInfo",
    "Position",
    "ScheduleTask",
    "SettingsInfo",
    "StatisticsInfo",
    "StayOutZone",
    "SystemInfo",
    "WorkArea",
]
