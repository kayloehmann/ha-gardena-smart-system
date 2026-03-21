"""Data models for Gardena Smart System API objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _attr(data: dict[str, Any], key: str) -> Any:
    """Extract the `value` from a Gardena attribute object, or None if absent."""
    obj = data.get(key)
    if obj is None:
        return None
    return obj.get("value")


@dataclass
class Location:
    """A Gardena location (garden)."""

    location_id: str
    name: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Location:
        """Parse from a JSON:API resource object."""
        return cls(
            location_id=data["id"],
            name=data["attributes"]["name"]["value"]
            if isinstance(data["attributes"].get("name"), dict)
            else data["attributes"].get("name", ""),
        )


@dataclass
class CommonService:
    """The COMMON service present on every Gardena device."""

    device_id: str
    name: str
    serial: str
    model_type: str
    battery_level: int | None
    battery_state: str | None
    rf_link_level: int | None
    rf_link_state: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> CommonService:
        """Parse from a JSON:API included object of type COMMON."""
        attrs = data["attributes"]
        device_id = data["relationships"]["device"]["data"]["id"]
        return cls(
            device_id=device_id,
            name=_attr(attrs, "name") or "",
            serial=_attr(attrs, "serial") or "",
            model_type=_attr(attrs, "modelType") or "",
            battery_level=_attr(attrs, "batteryLevel"),
            battery_state=_attr(attrs, "batteryState"),
            rf_link_level=_attr(attrs, "rfLinkLevel"),
            rf_link_state=_attr(attrs, "rfLinkState"),
        )

    def update_from_api(self, data: dict[str, Any]) -> None:
        """Apply a partial WebSocket update."""
        attrs = data["attributes"]
        if "name" in attrs:
            self.name = _attr(attrs, "name") or self.name
        if "batteryLevel" in attrs:
            self.battery_level = _attr(attrs, "batteryLevel")
        if "batteryState" in attrs:
            self.battery_state = _attr(attrs, "batteryState")
        if "rfLinkLevel" in attrs:
            self.rf_link_level = _attr(attrs, "rfLinkLevel")
        if "rfLinkState" in attrs:
            self.rf_link_state = _attr(attrs, "rfLinkState")


@dataclass
class MowerService:
    """The MOWER service on a SILENO robotic mower."""

    service_id: str
    device_id: str
    activity: str | None
    state: str | None
    last_error_code: str | None
    operating_hours: int | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> MowerService:
        """Parse from a JSON:API included object of type MOWER."""
        attrs = data["attributes"]
        return cls(
            service_id=data["id"],
            device_id=data["relationships"]["device"]["data"]["id"],
            activity=_attr(attrs, "activity"),
            state=_attr(attrs, "state"),
            last_error_code=_attr(attrs, "lastErrorCode"),
            operating_hours=_attr(attrs, "operatingHours"),
        )

    def update_from_api(self, data: dict[str, Any]) -> None:
        """Apply a partial WebSocket update."""
        attrs = data["attributes"]
        if "activity" in attrs:
            self.activity = _attr(attrs, "activity")
        if "state" in attrs:
            self.state = _attr(attrs, "state")
        if "lastErrorCode" in attrs:
            self.last_error_code = _attr(attrs, "lastErrorCode")
        if "operatingHours" in attrs:
            self.operating_hours = _attr(attrs, "operatingHours")


@dataclass
class ValveService:
    """A single VALVE — one irrigation zone or a standalone water control."""

    service_id: str
    device_id: str
    name: str
    activity: str | None
    state: str | None
    duration: int | None
    last_error_code: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ValveService:
        """Parse from a JSON:API included object of type VALVE."""
        attrs = data["attributes"]
        raw_id = data["id"]
        device_id = raw_id.split(":")[0]
        return cls(
            service_id=raw_id,
            device_id=device_id,
            name=_attr(attrs, "name") or "",
            activity=_attr(attrs, "activity"),
            state=_attr(attrs, "state"),
            duration=_attr(attrs, "duration"),
            last_error_code=_attr(attrs, "lastErrorCode"),
        )

    def update_from_api(self, data: dict[str, Any]) -> None:
        """Apply a partial WebSocket update."""
        attrs = data["attributes"]
        if "name" in attrs:
            self.name = _attr(attrs, "name") or self.name
        if "activity" in attrs:
            self.activity = _attr(attrs, "activity")
        if "state" in attrs:
            self.state = _attr(attrs, "state")
        if "duration" in attrs:
            self.duration = _attr(attrs, "duration")
        if "lastErrorCode" in attrs:
            self.last_error_code = _attr(attrs, "lastErrorCode")


@dataclass
class ValveSetService:
    """The VALVE_SET service that groups valves on a multi-zone irrigation controller."""

    service_id: str
    device_id: str
    state: str | None
    last_error_code: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ValveSetService:
        """Parse from a JSON:API included object of type VALVE_SET."""
        attrs = data["attributes"]
        device_id = data["relationships"]["device"]["data"]["id"]
        return cls(
            service_id=data["id"],
            device_id=device_id,
            state=_attr(attrs, "state"),
            last_error_code=_attr(attrs, "lastErrorCode"),
        )

    def update_from_api(self, data: dict[str, Any]) -> None:
        """Apply a partial WebSocket update."""
        attrs = data["attributes"]
        if "state" in attrs:
            self.state = _attr(attrs, "state")
        if "lastErrorCode" in attrs:
            self.last_error_code = _attr(attrs, "lastErrorCode")


@dataclass
class SensorService:
    """The SENSOR service on a Smart Sensor or Soil Sensor."""

    service_id: str
    device_id: str
    soil_humidity: int | None
    soil_temperature: float | None
    ambient_temperature: float | None
    light_intensity: int | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> SensorService:
        """Parse from a JSON:API included object of type SENSOR."""
        attrs = data["attributes"]
        device_id = data["relationships"]["device"]["data"]["id"]
        return cls(
            service_id=data["id"],
            device_id=device_id,
            soil_humidity=_attr(attrs, "soilHumidity"),
            soil_temperature=_attr(attrs, "soilTemperature"),
            ambient_temperature=_attr(attrs, "ambientTemperature"),
            light_intensity=_attr(attrs, "lightIntensity"),
        )

    def update_from_api(self, data: dict[str, Any]) -> None:
        """Apply a partial WebSocket update."""
        attrs = data["attributes"]
        if "soilHumidity" in attrs:
            self.soil_humidity = _attr(attrs, "soilHumidity")
        if "soilTemperature" in attrs:
            self.soil_temperature = _attr(attrs, "soilTemperature")
        if "ambientTemperature" in attrs:
            self.ambient_temperature = _attr(attrs, "ambientTemperature")
        if "lightIntensity" in attrs:
            self.light_intensity = _attr(attrs, "lightIntensity")


@dataclass
class PowerSocketService:
    """The POWER_SOCKET service on a Smart Power Outlet."""

    service_id: str
    device_id: str
    activity: str | None
    state: str | None
    duration: int | None
    last_error_code: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PowerSocketService:
        """Parse from a JSON:API included object of type POWER_SOCKET."""
        attrs = data["attributes"]
        device_id = data["relationships"]["device"]["data"]["id"]
        return cls(
            service_id=data["id"],
            device_id=device_id,
            activity=_attr(attrs, "activity"),
            state=_attr(attrs, "state"),
            duration=_attr(attrs, "duration"),
            last_error_code=_attr(attrs, "lastErrorCode"),
        )

    def update_from_api(self, data: dict[str, Any]) -> None:
        """Apply a partial WebSocket update."""
        attrs = data["attributes"]
        if "activity" in attrs:
            self.activity = _attr(attrs, "activity")
        if "state" in attrs:
            self.state = _attr(attrs, "state")
        if "duration" in attrs:
            self.duration = _attr(attrs, "duration")
        if "lastErrorCode" in attrs:
            self.last_error_code = _attr(attrs, "lastErrorCode")


@dataclass
class Schedule:
    """A scheduled event for a Gardena device."""

    schedule_id: str
    start_at: str
    end_at: str
    weekdays: list[str]
    valve_id: int | None
    paused_until: str | None = None

    @property
    def is_paused(self) -> bool:
        """True if this schedule is currently paused."""
        if not self.paused_until:
            return False
        try:
            ts = datetime.fromisoformat(self.paused_until.replace("Z", "+00:00"))
            return ts > datetime.now(timezone.utc)
        except ValueError:
            return False

    @property
    def paused_until_date(self) -> str | None:
        """Return the pause end date, or None if paused indefinitely or not paused."""
        if not self.is_paused:
            return None
        try:
            ts = datetime.fromisoformat(self.paused_until.replace("Z", "+00:00"))
            if ts.year >= 2038:
                return None
            return self.paused_until
        except ValueError:
            return None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Schedule:
        """Parse from a schedule object in the device response."""
        recurrence = data.get("recurrence", {})
        return cls(
            schedule_id=str(data.get("id", "")),
            start_at=data.get("start_at", ""),
            end_at=data.get("end_at", ""),
            weekdays=recurrence.get("weekdays", []),
            valve_id=data.get("valve_id"),
        )


@dataclass
class Device:
    """A Gardena physical device with all its associated services."""

    device_id: str
    location_id: str
    common: CommonService | None = None
    mower: MowerService | None = None
    valves: dict[str, ValveService] = field(default_factory=dict)
    valve_set: ValveSetService | None = None
    sensor: SensorService | None = None
    power_socket: PowerSocketService | None = None
    schedules: list[Schedule] = field(default_factory=list)

    @property
    def name(self) -> str:
        """Human-readable name from the COMMON service."""
        if self.common:
            return self.common.name
        return self.device_id

    @property
    def serial(self) -> str:
        """Device serial number."""
        if self.common:
            return self.common.serial
        return ""

    @property
    def model(self) -> str:
        """Device model string."""
        if self.common:
            return self.common.model_type
        return ""

    @property
    def is_online(self) -> bool:
        """True if the device's RF link is online."""
        if self.common:
            return self.common.rf_link_state == "ONLINE"
        return False
