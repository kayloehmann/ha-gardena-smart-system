"""Diagnostics for the Gardena Smart System integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import GardenaConfigEntry
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE

TO_REDACT = {
    "client_id",
    "client_secret",
    "serial",
    "serial_number",
    "location_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    api_type = entry.data.get(CONF_API_TYPE)
    coordinator = entry.runtime_data

    if api_type == API_TYPE_AUTOMOWER:
        devices_data = _serialize_automower_devices(coordinator.data)
    else:
        devices_data = _serialize_gardena_devices(coordinator.data)

    return async_redact_data(
        {
            "config_entry": entry.as_dict(),
            "devices": devices_data,
        },
        TO_REDACT,
    )


def _serialize_gardena_devices(
    data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Serialize Gardena device data for diagnostics."""
    if not data:
        return {}

    devices_data: dict[str, Any] = {}
    for device_id, device in data.items():
        devices_data[device_id] = async_redact_data(
            {
                "name": device.name,
                "model": device.model,
                "serial": device.serial,
                "is_online": device.is_online,
                "common": _service_to_dict(device.common),
                "mower": _service_to_dict(device.mower),
                "sensor": _service_to_dict(device.sensor),
                "power_socket": _service_to_dict(device.power_socket),
                "valve_set": _service_to_dict(device.valve_set),
                "valves": {
                    sid: _service_to_dict(v) for sid, v in device.valves.items()
                },
            },
            TO_REDACT,
        )
    return devices_data


def _serialize_automower_devices(
    data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Serialize Automower device data for diagnostics."""
    if not data:
        return {}

    devices_data: dict[str, Any] = {}
    for mower_id, device in data.items():
        devices_data[mower_id] = async_redact_data(
            {
                "name": device.name,
                "model": device.model,
                "serial_number": device.serial_number,
                "is_connected": device.is_connected,
                "battery": asdict(device.battery),
                "mower": asdict(device.mower),
                "planner": {
                    "next_start_timestamp": str(
                        device.planner.next_start_timestamp
                    ),
                    "restricted_reason": device.planner.restricted_reason,
                    "override_action": device.planner.override.action,
                },
                "statistics": asdict(device.statistics),
                "settings": asdict(device.settings),
                "capabilities": asdict(device.capabilities),
                "positions_count": len(device.positions),
                "work_areas": {
                    str(wa_id): {
                        "name": wa.name,
                        "cutting_height": wa.cutting_height,
                    }
                    for wa_id, wa in device.work_areas.items()
                },
                "stay_out_zones": {
                    z_id: {"name": z.name, "enabled": z.enabled}
                    for z_id, z in device.stay_out_zones.items()
                },
                "schedule_tasks_count": len(device.calendar.tasks),
            },
            TO_REDACT,
        )
    return devices_data


def _service_to_dict(service: Any) -> dict[str, Any] | None:
    """Convert a service dataclass to a dict, or return None."""
    if service is None:
        return None
    return {k: v for k, v in vars(service).items()}
