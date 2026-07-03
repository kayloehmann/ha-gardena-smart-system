"""Tests for cloud<->local command and state translation."""

from typing import Any

from aiogardenasmart.const import ControlType, ValveActivity

from aiogardenasmart import Device, SensorService, ValveService
from custom_components.gardena_smart_system_ng.local_translate import (
    CMD_START,
    CMD_STOP,
    apply_local_state,
    build_local_command,
    local_valve_position,
    sorted_valve_service_ids,
)


class FakeLocalDevice:
    """A stand-in local-library device recording builder calls."""

    def __init__(self, *, valve_ids: list[int] | None = None) -> None:
        self.valve_ids = valve_ids if valve_ids is not None else []
        self.calls: list[tuple[Any, ...]] = []
        self._open: dict[int, bool | None] = {}
        self.online: bool | None = None
        self.soil_moisture: int | None = None
        self.temperature: int | None = None

    # command builders
    def build_open_valve_obj(self, valve_id: int, seconds: int) -> str:
        self.calls.append(("open", valve_id, seconds))
        return f"open:{valve_id}:{seconds}"

    def build_close_valve_obj(self, valve_id: int) -> str:
        self.calls.append(("close", valve_id))
        return f"close:{valve_id}"

    def build_enable_output_obj(self, seconds: int) -> str:
        self.calls.append(("enable", seconds))
        return f"enable:{seconds}"

    def build_disable_output_obj(self) -> str:
        self.calls.append(("disable",))
        return "disable"

    def build_start_mowing_obj(self, seconds: int) -> str:
        self.calls.append(("mow", seconds))
        return f"mow:{seconds}"

    def build_stop_mowing_obj(self) -> str:
        self.calls.append(("park",))
        return "park"

    # accessors
    def is_valve_open(self, valve_id: int) -> bool | None:
        return self._open.get(valve_id)

    def is_online(self) -> bool | None:
        return self.online


def _valve(service_id: str, activity: str) -> ValveService:
    return ValveService(
        service_id=service_id,
        device_id=service_id.split(":")[0],
        name="v",
        activity=activity,
        state="OK",
        duration=None,
        duration_timestamp=None,
        last_error_code=None,
    )


def _device_with_valves(activities: dict[str, str]) -> Device:
    return Device(
        device_id="uuid",
        location_id="loc",
        valves={sid: _valve(sid, act) for sid, act in activities.items()},
    )


def test_valves_sorted_by_numeric_suffix() -> None:
    device = _device_with_valves({"uuid:10": "CLOSED", "uuid:2": "CLOSED", "uuid:1": "CLOSED"})
    assert sorted_valve_service_ids(device) == ["uuid:1", "uuid:2", "uuid:10"]
    assert local_valve_position(device, "uuid:2") == 1
    assert local_valve_position(device, "uuid:99") is None


def test_valve_open_maps_to_positional_local_valve() -> None:
    device = _device_with_valves({"uuid:1": "CLOSED", "uuid:2": "CLOSED"})
    local = FakeLocalDevice(valve_ids=[0, 1])
    result = build_local_command(local, device, "uuid:2", ControlType.VALVE, CMD_START, seconds=600)
    assert result == "open:1:600"  # 2nd cloud valve → 2nd local valve (id 1)
    assert local.calls == [("open", 1, 600)]


def test_valve_close_maps_to_close_builder() -> None:
    device = _device_with_valves({"uuid:1": "MANUAL_WATERING"})
    local = FakeLocalDevice(valve_ids=[0])
    result = build_local_command(local, device, "uuid:1", ControlType.VALVE, CMD_STOP, seconds=None)
    assert result == "close:0"


def test_power_socket_commands() -> None:
    device = Device(device_id="uuid", location_id="loc")
    local = FakeLocalDevice()
    assert (
        build_local_command(local, device, "uuid", ControlType.POWER_SOCKET, CMD_START, seconds=300)
        == "enable:300"
    )
    assert (
        build_local_command(local, device, "uuid", ControlType.POWER_SOCKET, CMD_STOP, seconds=None)
        == "disable"
    )


def test_unmappable_command_returns_none() -> None:
    device = _device_with_valves({"uuid:1": "CLOSED"})
    local = FakeLocalDevice(valve_ids=[0])
    # Unknown command verb → cloud fallback.
    assert (
        build_local_command(local, device, "uuid:1", ControlType.VALVE, "START_DONT_OVERRIDE", None)
        is None
    )


def test_state_overlay_flips_valve_activity() -> None:
    device = _device_with_valves(
        {"uuid:1": ValveActivity.CLOSED, "uuid:2": ValveActivity.MANUAL_WATERING}
    )
    local = FakeLocalDevice(valve_ids=[0, 1])
    local._open = {0: True, 1: False}  # local says v0 open, v1 closed

    assert apply_local_state(local, device) is True
    assert device.valves["uuid:1"].activity == ValveActivity.MANUAL_WATERING
    assert device.valves["uuid:2"].activity == ValveActivity.CLOSED


def test_state_overlay_preserves_agreeing_scheduled_label() -> None:
    device = _device_with_valves({"uuid:1": ValveActivity.SCHEDULED_WATERING})
    local = FakeLocalDevice(valve_ids=[0])
    local._open = {0: True}  # both agree the valve is open

    assert apply_local_state(local, device) is False
    # Scheduled label must NOT be downgraded to manual when they agree.
    assert device.valves["uuid:1"].activity == ValveActivity.SCHEDULED_WATERING


def test_mower_start_and_park() -> None:
    device = Device(device_id="uuid", location_id="loc")
    local = FakeLocalDevice()
    assert (
        build_local_command(local, device, "uuid", ControlType.MOWER, CMD_START, seconds=900)
        == "mow:900"
    )
    assert (
        build_local_command(
            local, device, "uuid", ControlType.MOWER, "PARK_UNTIL_FURTHER_NOTICE", None
        )
        == "park"
    )


def test_unknown_control_type_returns_none() -> None:
    device = Device(device_id="uuid", location_id="loc")
    local = FakeLocalDevice()
    assert build_local_command(local, device, "uuid", "LIGHT_CONTROL", CMD_START, 60) is None


def test_valve_command_none_when_position_missing() -> None:
    device = _device_with_valves({"uuid:1": "CLOSED"})
    local = FakeLocalDevice(valve_ids=[0])
    # service_id not present on the device → no positional match → cloud fallback
    assert build_local_command(local, device, "uuid:9", ControlType.VALVE, CMD_STOP, None) is None


def test_call_returns_none_when_builder_absent() -> None:
    device = Device(device_id="uuid", location_id="loc")

    class Bare:  # a local object lacking any command builders
        pass

    assert (
        build_local_command(Bare(), device, "uuid", ControlType.POWER_SOCKET, CMD_STOP, None)
        is None
    )


def test_state_overlay_updates_sensor_values() -> None:
    device = Device(
        device_id="uuid",
        location_id="loc",
        sensor=SensorService(
            service_id="uuid:sensor",
            device_id="uuid",
            soil_humidity=None,
            soil_temperature=None,
            ambient_temperature=None,
            light_intensity=None,
        ),
    )
    local = FakeLocalDevice()
    local.soil_moisture = 55
    local.temperature = 24

    assert apply_local_state(local, device) is True
    assert device.sensor is not None
    assert device.sensor.soil_humidity == 55
    assert device.sensor.soil_temperature == 24.0
