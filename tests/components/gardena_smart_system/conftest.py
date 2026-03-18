"""Shared fixtures for Gardena Smart System integration tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import MockConfigEntry  # type: ignore[no-redef]

from custom_components.gardena_smart_system.const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_LOCATION_ID,
    DOMAIN,
)

MOCK_CLIENT_ID = "test-client-id"
MOCK_CLIENT_SECRET = "test-client-secret"
MOCK_LOCATION_ID = "location-uuid-1234"
MOCK_LOCATION_NAME = "My Garden"

ENTRY_DATA = {
    CONF_CLIENT_ID: MOCK_CLIENT_ID,
    CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET,
    CONF_LOCATION_ID: MOCK_LOCATION_ID,
}


def make_mock_device(
    device_id: str = "device-uuid",
    serial: str = "SN001",
    name: str = "My Sensor",
    *,
    has_sensor: bool = True,
    has_mower: bool = False,
    has_power_socket: bool = False,
    valve_count: int = 0,
) -> MagicMock:
    """Build a Device mock with the requested services populated."""
    device = MagicMock()
    device.device_id = device_id
    device.serial = serial
    device.name = name
    device.is_online = True

    common = MagicMock()
    common.name = name
    common.serial = serial
    common.model_type = "GARDENA smart Sensor"
    common.battery_level = 85
    common.battery_state = "OK"
    common.rf_link_level = 60
    common.rf_link_state = "ONLINE"
    device.common = common
    device.model = common.model_type

    if has_sensor:
        sensor = MagicMock()
        sensor.soil_humidity = 42
        sensor.soil_temperature = 18.5
        sensor.ambient_temperature = 22.1
        sensor.light_intensity = 15000
        device.sensor = sensor
    else:
        device.sensor = None

    if has_mower:
        mower = MagicMock()
        mower.service_id = device_id
        mower.device_id = device_id
        mower.activity = "PARKED_PARK_SELECTED"
        mower.state = "OK"
        mower.operating_hours = 100
        device.mower = mower
    else:
        device.mower = None

    if has_power_socket:
        ps = MagicMock()
        ps.service_id = device_id
        ps.activity = "OFF"
        ps.state = "OK"
        device.power_socket = ps
    else:
        device.power_socket = None

    valves: dict[str, MagicMock] = {}
    for i in range(1, valve_count + 1):
        vid = f"{device_id}:{i}"
        valve = MagicMock()
        valve.service_id = vid
        valve.name = f"Valve {i}"
        valve.activity = "CLOSED"
        valve.state = "OK"
        valves[vid] = valve
    device.valves = valves
    device.valve_set = None

    return device


def make_mock_location(
    location_id: str = MOCK_LOCATION_ID,
    name: str = MOCK_LOCATION_NAME,
) -> MagicMock:
    """Build a Location mock."""
    loc = MagicMock()
    loc.location_id = location_id
    loc.name = name
    return loc


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a MockConfigEntry for the Gardena integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        title=MOCK_LOCATION_NAME,
    )


@pytest.fixture
def mock_sensor_device() -> MagicMock:
    """Return a single sensor Device mock."""
    return make_mock_device()


@pytest.fixture
def mock_devices(mock_sensor_device: MagicMock) -> dict[str, MagicMock]:
    """Return a device map with one sensor device."""
    return {mock_sensor_device.device_id: mock_sensor_device}
