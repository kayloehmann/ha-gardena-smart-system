"""Diagnostics for the Gardena Smart System integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import GardenaConfigEntry

TO_REDACT = {
    "client_id",
    "client_secret",
    "serial",
    "location_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    devices_data: dict[str, Any] = {}
    if coordinator.data:
        for device_id, device in coordinator.data.items():
            devices_data[device_id] = {
                "name": device.name,
                "model": device.model,
                "is_online": device.is_online,
                "common": _service_to_dict(device.common),
                "mower": _service_to_dict(device.mower),
                "sensor": _service_to_dict(device.sensor),
                "power_socket": _service_to_dict(device.power_socket),
                "valve_set": _service_to_dict(device.valve_set),
                "valves": {
                    sid: _service_to_dict(v) for sid, v in device.valves.items()
                },
            }

    return async_redact_data(
        {
            "config_entry": entry.as_dict(),
            "devices": devices_data,
        },
        TO_REDACT,
    )


def _service_to_dict(service: Any) -> dict[str, Any] | None:
    """Convert a service dataclass to a dict, or return None."""
    if service is None:
        return None
    return {k: v for k, v in vars(service).items()}
