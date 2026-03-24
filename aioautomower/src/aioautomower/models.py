"""Data models for Husqvarna Automower Connect API objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _ts_to_datetime(ts: int | None) -> datetime | None:
    """Convert a millisecond Unix timestamp to a UTC datetime, or None."""
    if ts is None or ts == 0:
        return None
    return datetime.fromtimestamp(ts / 1000, tz=UTC)


@dataclass
class Position:
    """A GPS position sample."""

    latitude: float
    longitude: float

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Position:
        return cls(
            latitude=float(data.get("latitude", 0)),
            longitude=float(data.get("longitude", 0)),
        )


@dataclass
class SystemInfo:
    """System information for an Automower."""

    name: str
    model: str
    serial_number: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> SystemInfo:
        return cls(
            name=data.get("name", ""),
            model=data.get("model", ""),
            serial_number=data.get("serialNumber", ""),
        )


@dataclass
class BatteryInfo:
    """Battery state."""

    level: int

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> BatteryInfo:
        return cls(level=int(data.get("batteryPercent", 0)))


@dataclass
class MowerInfo:
    """Mower operational state."""

    mode: str
    activity: str
    state: str
    error_code: int
    error_code_timestamp: datetime | None
    inactive_reason: str | None
    is_error_confirmable: bool

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> MowerInfo:
        return cls(
            mode=data.get("mode", "UNKNOWN"),
            activity=data.get("activity", "UNKNOWN"),
            state=data.get("state", "UNKNOWN"),
            error_code=int(data.get("errorCode", 0)),
            error_code_timestamp=_ts_to_datetime(data.get("errorCodeTimestamp")),
            inactive_reason=data.get("inactiveReason"),
            is_error_confirmable=bool(data.get("isErrorConfirmable", False)),
        )


@dataclass
class ScheduleTask:
    """A single calendar schedule entry."""

    start: int
    duration: int
    monday: bool
    tuesday: bool
    wednesday: bool
    thursday: bool
    friday: bool
    saturday: bool
    sunday: bool
    work_area_id: int | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ScheduleTask:
        return cls(
            start=int(data.get("start", 0)),
            duration=int(data.get("duration", 0)),
            monday=bool(data.get("monday", False)),
            tuesday=bool(data.get("tuesday", False)),
            wednesday=bool(data.get("wednesday", False)),
            thursday=bool(data.get("thursday", False)),
            friday=bool(data.get("friday", False)),
            saturday=bool(data.get("saturday", False)),
            sunday=bool(data.get("sunday", False)),
            work_area_id=data.get("workAreaId"),
        )


@dataclass
class CalendarInfo:
    """Mowing schedule calendar."""

    tasks: list[ScheduleTask]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> CalendarInfo:
        tasks_data = data.get("tasks", [])
        return cls(tasks=[ScheduleTask.from_api(t) for t in tasks_data])


@dataclass
class PlannerOverride:
    """Planner override state."""

    action: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PlannerOverride:
        return cls(action=data.get("action", "NOT_ACTIVE"))


@dataclass
class PlannerInfo:
    """Mowing planner state."""

    next_start_timestamp: datetime | None
    override: PlannerOverride
    restricted_reason: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PlannerInfo:
        override_data = data.get("override", {})
        return cls(
            next_start_timestamp=_ts_to_datetime(data.get("nextStartTimestamp")),
            override=PlannerOverride.from_api(override_data),
            restricted_reason=data.get("restrictedReason", "NONE"),
        )


@dataclass
class MetadataInfo:
    """Device metadata (connectivity)."""

    connected: bool
    status_timestamp: datetime | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> MetadataInfo:
        return cls(
            connected=bool(data.get("connected", False)),
            status_timestamp=_ts_to_datetime(data.get("statusTimestamp")),
        )


@dataclass
class StatisticsInfo:
    """Mower usage statistics."""

    cutting_blade_usage_time: int
    number_of_charging_cycles: int
    number_of_collisions: int
    total_charging_time: int
    total_cutting_time: int
    total_drive_distance: int
    total_running_time: int
    total_searching_time: int

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> StatisticsInfo:
        return cls(
            cutting_blade_usage_time=int(data.get("cuttingBladeUsageTime", 0)),
            number_of_charging_cycles=int(data.get("numberOfChargingCycles", 0)),
            number_of_collisions=int(data.get("numberOfCollisions", 0)),
            total_charging_time=int(data.get("totalChargingTime", 0)),
            total_cutting_time=int(data.get("totalCuttingTime", 0)),
            total_drive_distance=int(data.get("totalDriveDistance", 0)),
            total_running_time=int(data.get("totalRunningTime", 0)),
            total_searching_time=int(data.get("totalSearchingTime", 0)),
        )


@dataclass
class SettingsInfo:
    """Mower settings."""

    cutting_height: int
    headlight_mode: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> SettingsInfo:
        headlight = data.get("headlight", {})
        return cls(
            cutting_height=int(data.get("cuttingHeight", 0)),
            headlight_mode=headlight.get("mode", "ALWAYS_OFF"),
        )


@dataclass
class WorkArea:
    """A named work area with individual cutting height."""

    work_area_id: int
    name: str
    cutting_height: int
    enabled: bool

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> WorkArea:
        return cls(
            work_area_id=int(data.get("workAreaId", 0)),
            name=data.get("name", ""),
            cutting_height=int(data.get("cuttingHeight", 0)),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class StayOutZone:
    """A stay-out zone that can be enabled or disabled."""

    zone_id: str
    name: str
    enabled: bool

    @classmethod
    def from_api(cls, zone_id: str, data: dict[str, Any]) -> StayOutZone:
        return cls(
            zone_id=zone_id,
            name=data.get("name", ""),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class CapabilitiesInfo:
    """Model-specific feature capabilities."""

    headlights: bool
    work_areas: bool
    stay_out_zones: bool
    position: bool
    can_confirm_error: bool

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> CapabilitiesInfo:
        return cls(
            headlights=bool(data.get("headlights", False)),
            work_areas=bool(data.get("workAreas", False)),
            stay_out_zones=bool(data.get("stayOutZones", False)),
            position=bool(data.get("position", False)),
            can_confirm_error=bool(data.get("canConfirmError", False)),
        )


@dataclass
class AutomowerDevice:
    """A Husqvarna Automower with all its data."""

    mower_id: str
    system: SystemInfo
    battery: BatteryInfo
    mower: MowerInfo
    calendar: CalendarInfo
    planner: PlannerInfo
    metadata: MetadataInfo
    positions: list[Position]
    statistics: StatisticsInfo
    settings: SettingsInfo
    capabilities: CapabilitiesInfo
    work_areas: dict[int, WorkArea] = field(default_factory=dict)
    stay_out_zones: dict[str, StayOutZone] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """Human-readable name."""
        return self.system.name

    @property
    def serial_number(self) -> str:
        """Device serial number."""
        return self.system.serial_number

    @property
    def model(self) -> str:
        """Device model string."""
        return self.system.model

    @property
    def is_connected(self) -> bool:
        """True if the device is currently connected to the cloud."""
        return self.metadata.connected

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> AutomowerDevice:
        """Parse from a GET /mowers response item."""
        mower_id = data.get("id", "")
        attrs = data.get("attributes", {})

        # Parse work areas
        work_areas: dict[int, WorkArea] = {}
        for wa_data in attrs.get("workAreas", []):
            wa = WorkArea.from_api(wa_data)
            work_areas[wa.work_area_id] = wa

        # Parse stay-out zones
        stay_out_zones: dict[str, StayOutZone] = {}
        soz_data = attrs.get("stayOutZones", {})
        if isinstance(soz_data, dict):
            for zone_id, zone_data in soz_data.get("zones", {}).items():
                stay_out_zones[zone_id] = StayOutZone.from_api(zone_id, zone_data)

        # Parse positions
        positions = [Position.from_api(p) for p in attrs.get("positions", [])]

        return cls(
            mower_id=mower_id,
            system=SystemInfo.from_api(attrs.get("system", {})),
            battery=BatteryInfo.from_api(attrs.get("battery", {})),
            mower=MowerInfo.from_api(attrs.get("mower", {})),
            calendar=CalendarInfo.from_api(attrs.get("calendar", {})),
            planner=PlannerInfo.from_api(attrs.get("planner", {})),
            metadata=MetadataInfo.from_api(attrs.get("metadata", {})),
            positions=positions,
            statistics=StatisticsInfo.from_api(attrs.get("statistics", {})),
            settings=SettingsInfo.from_api(attrs.get("settings", {})),
            capabilities=CapabilitiesInfo.from_api(attrs.get("capabilities", {})),
            work_areas=work_areas,
            stay_out_zones=stay_out_zones,
        )

    def update_from_api(self, data: dict[str, Any]) -> None:
        """Apply a partial update from a WebSocket message or REST response."""
        attrs = data.get("attributes", data)

        if "battery" in attrs:
            self.battery = BatteryInfo.from_api(attrs["battery"])
        if "mower" in attrs:
            self.mower = MowerInfo.from_api(attrs["mower"])
        if "calendar" in attrs:
            self.calendar = CalendarInfo.from_api(attrs["calendar"])
        if "planner" in attrs:
            self.planner = PlannerInfo.from_api(attrs["planner"])
        if "metadata" in attrs:
            self.metadata = MetadataInfo.from_api(attrs["metadata"])
        if "positions" in attrs:
            self.positions = [Position.from_api(p) for p in attrs["positions"]]
        if "statistics" in attrs:
            self.statistics = StatisticsInfo.from_api(attrs["statistics"])
        if "settings" in attrs:
            self.settings = SettingsInfo.from_api(attrs["settings"])
