"""Translation between the cloud device model and the local gateway model.

Two directions, both pure and unit-testable:

* **Command** (cloud → local): turn a cloud command
  ``(service_id, control_type, command, seconds)`` — exactly what the entity
  platforms already produce for ``client.async_send_command`` — into a local
  ``EgressMessageList`` built by the official ``gardena-smart-local-api``.
  Returns ``None`` when the command cannot be expressed locally, so the caller
  falls back to the proven cloud path.

* **State** (local → cloud): overlay fresh local device state onto the cloud
  ``Device`` model the entities read, so a connected local link makes state
  update instantly and survive a cloud/internet outage.

Valve identity is the one correspondence not carried by a shared id: the cloud
addresses valves by ``service_id`` suffix (``uuid:1``…), the local library by a
0-based ``valve_id``. We map them **positionally** — the k-th cloud valve (by
sorted integer suffix) is the k-th local valve — which is robust to whether the
cloud suffix is 0- or 1-based. This assumes both sides enumerate a device's
valves in the same physical order (they do in practice); it is the single
assumption worth re-checking against live data before trusting local control of
a multi-valve controller.
"""

from __future__ import annotations

from typing import Any

from aiogardenasmart.const import ControlType, ValveActivity
from gardena_smart_local_api.messages import EgressMessageList

from aiogardenasmart import Device as CloudDevice

from .local_ids import cloud_serial_from_local_id

# Cloud command verbs (see coordinator._MQTT_DISPATCH / valve.py / switch.py).
CMD_START = "START_SECONDS_TO_OVERRIDE"
CMD_STOP = "STOP_UNTIL_NEXT_TASK"

# Cloud valve activities that mean "water is flowing" (see valve.py.is_closed).
_WATERING_ACTIVITIES = frozenset({ValveActivity.MANUAL_WATERING, ValveActivity.SCHEDULED_WATERING})


def index_local_devices_by_serial(local_devices: Any) -> dict[str, Any]:
    """Map cloud serial → local device object for every decodable local device."""
    mapping: dict[str, Any] = {}
    for device in local_devices.values():
        serial = cloud_serial_from_local_id(device.id)
        if serial is not None:
            mapping[serial] = device
    return mapping


def sorted_valve_service_ids(cloud_device: CloudDevice) -> list[str]:
    """Cloud valve service_ids ordered by their integer suffix (``uuid:1`` → 1)."""

    def _suffix(service_id: str) -> int:
        tail = service_id.rsplit(":", 1)[-1]
        return int(tail) if tail.isdigit() else -1

    return sorted(cloud_device.valves, key=_suffix)


def local_valve_position(cloud_device: CloudDevice, service_id: str) -> int | None:
    """Positional index of a cloud valve within its device, or ``None``."""
    ordered = sorted_valve_service_ids(cloud_device)
    return ordered.index(service_id) if service_id in ordered else None


def build_local_command(
    local_device: Any,
    cloud_device: CloudDevice,
    service_id: str,
    control_type: str,
    command: str,
    seconds: int | None,
) -> EgressMessageList | None:
    """Build the local egress for a cloud command, or ``None`` if not mappable."""
    if control_type == ControlType.VALVE:
        return _build_valve_command(local_device, cloud_device, service_id, command, seconds)
    if control_type == ControlType.POWER_SOCKET:
        if command == CMD_START and seconds is not None:
            return _call(local_device, "build_enable_output_obj", seconds)
        if command == CMD_STOP:
            return _call(local_device, "build_disable_output_obj")
        return None
    if control_type == ControlType.MOWER:
        # Local start needs an explicit duration; park maps to stop-mowing.
        # Anything else (e.g. START_DONT_OVERRIDE) is left to the cloud path.
        if command == CMD_START and seconds is not None:
            return _call(local_device, "build_start_mowing_obj", seconds)
        if command.startswith("PARK"):
            return _call(local_device, "build_stop_mowing_obj")
        return None
    return None


def _build_valve_command(
    local_device: Any,
    cloud_device: CloudDevice,
    service_id: str,
    command: str,
    seconds: int | None,
) -> EgressMessageList | None:
    position = local_valve_position(cloud_device, service_id)
    valve_ids = getattr(local_device, "valve_ids", None)
    if position is None or not valve_ids or position >= len(valve_ids):
        return None
    valve_id = valve_ids[position]
    if command == CMD_START and seconds is not None:
        return _call(local_device, "build_open_valve_obj", valve_id, seconds)
    if command == CMD_STOP:
        return _call(local_device, "build_close_valve_obj", valve_id)
    return None


def _call(obj: Any, method: str, *args: Any) -> EgressMessageList | None:
    """Call a local-library builder if the device supports it."""
    builder = getattr(obj, method, None)
    if builder is None:
        return None
    result: EgressMessageList = builder(*args)
    return result


def apply_local_state(local_device: Any, cloud_device: CloudDevice) -> bool:
    """Overlay fresh local state onto the cloud device model. Returns changed.

    Conservative by design: it only asserts the facts the local model states
    unambiguously (link online, valve open/closed, soil sensor values) and
    leaves richer cloud-only labels (manual vs scheduled watering) untouched
    when local and cloud already agree on open/closed.
    """
    changed = False
    changed |= _overlay_online(local_device, cloud_device)
    changed |= _overlay_valves(local_device, cloud_device)
    changed |= _overlay_sensor(local_device, cloud_device)
    return changed


def _overlay_online(local_device: Any, cloud_device: CloudDevice) -> bool:
    online = _safe(local_device, "is_online")
    common = cloud_device.common
    if online is None or common is None:
        return False
    desired = "ONLINE" if online else "OFFLINE"
    if common.rf_link_state != desired:
        common.rf_link_state = desired
        return True
    return False


def _overlay_valves(local_device: Any, cloud_device: CloudDevice) -> bool:
    valve_ids = getattr(local_device, "valve_ids", None)
    if not valve_ids or not cloud_device.valves:
        return False
    changed = False
    for position, service_id in enumerate(sorted_valve_service_ids(cloud_device)):
        if position >= len(valve_ids):
            break
        is_open = _safe(local_device, "is_valve_open", valve_ids[position])
        if is_open is None:
            continue
        valve = cloud_device.valves[service_id]
        if is_open and valve.activity == ValveActivity.CLOSED:
            valve.activity = ValveActivity.MANUAL_WATERING
            changed = True
        elif not is_open and valve.activity in _WATERING_ACTIVITIES:
            valve.activity = ValveActivity.CLOSED
            valve.duration = 0
            valve.duration_timestamp = None
            changed = True
    return changed


def _overlay_sensor(local_device: Any, cloud_device: CloudDevice) -> bool:
    sensor = cloud_device.sensor
    if sensor is None:
        return False
    changed = False
    moisture = _prop(local_device, "soil_moisture")
    if moisture is not None and sensor.soil_humidity != moisture:
        sensor.soil_humidity = moisture
        changed = True
    temperature = _prop(local_device, "temperature")
    if temperature is not None and sensor.soil_temperature != temperature:
        sensor.soil_temperature = float(temperature)
        changed = True
    return changed


def _safe(obj: Any, method: str, *args: Any) -> Any:
    """Call an accessor method, returning None if the device lacks it."""
    accessor = getattr(obj, method, None)
    return accessor(*args) if callable(accessor) else None


def _prop(obj: Any, name: str) -> Any:
    """Read a property, returning None if the device lacks it."""
    return getattr(obj, name, None)
