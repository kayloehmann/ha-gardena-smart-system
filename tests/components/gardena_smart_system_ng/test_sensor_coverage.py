"""Coverage for the per-service sensor `native_value` None branches."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,  # type: ignore[no-redef]
    )

from custom_components.gardena_smart_system_ng.const import DOMAIN
from custom_components.gardena_smart_system_ng.coordinator import GardenaCoordinator
from custom_components.gardena_smart_system_ng.sensor import (
    GardenaPowerSocketRemainingDurationSensor,
    GardenaValveErrorSensor,
    GardenaValveRemainingDurationSensor,
    GardenaValveSetErrorSensor,
    GardenaValveStateSensor,
)

from .conftest import ENTRY_DATA, make_mock_device


@pytest.fixture
async def coord(hass: HomeAssistant) -> GardenaCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, title="My Garden")
    entry.add_to_hass(hass)
    coordinator = GardenaCoordinator(hass, entry, async_get_clientsession(hass))
    coordinator._auth = AsyncMock()
    return coordinator


def test_sensor_native_value_none_branches(coord: GardenaCoordinator) -> None:
    device = make_mock_device(valve_count=1, has_power_socket=True)
    device.valve_set = MagicMock()
    service_id = next(iter(device.valves))

    sensors = [
        GardenaValveRemainingDurationSensor(coord, device, service_id),
        GardenaValveErrorSensor(coord, device, service_id),
        GardenaValveStateSensor(coord, device, service_id),
        GardenaPowerSocketRemainingDurationSensor(coord, device),
        GardenaValveSetErrorSensor(coord, device),
    ]

    # 1) Device missing from coordinator data → `_device` is None.
    coord.data = {}
    for sensor in sensors:
        assert sensor.native_value is None

    # 2) Device present but its service objects are gone → second None branch.
    stripped = make_mock_device(valve_count=0, has_power_socket=False)
    stripped.valves = {}
    stripped.power_socket = None
    stripped.valve_set = None
    coord.data = {stripped.device_id: stripped}
    for sensor in sensors:
        assert sensor.native_value is None
