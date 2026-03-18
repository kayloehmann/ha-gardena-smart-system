"""Tests for Gardena data model parsing."""

from __future__ import annotations

import pytest

from aiogardenasmart.client import _parse_devices
from aiogardenasmart.models import (
    CommonService,
    Device,
    MowerService,
    PowerSocketService,
    SensorService,
    ValveService,
    ValveSetService,
)

from .fixtures import (
    IRRIGATION_DEVICE_ID,
    IRRIGATION_LOCATION_RESPONSE,
    LOCATION_ID,
    POWER_SOCKET_DEVICE_ID,
    POWER_SOCKET_LOCATION_RESPONSE,
    SENSOR_DEVICE_ID,
    SENSOR_LOCATION_RESPONSE,
    WATER_CONTROL_DEVICE_ID,
    WATER_CONTROL_LOCATION_RESPONSE,
)


class TestSensorDeviceParsing:
    def test_sensor_device_parsed(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        assert SENSOR_DEVICE_ID in devices

    def test_sensor_has_common_service(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        device = devices[SENSOR_DEVICE_ID]
        assert isinstance(device.common, CommonService)

    def test_common_service_fields(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        common = devices[SENSOR_DEVICE_ID].common
        assert common is not None
        assert common.name == "My Sensor"
        assert common.serial == "SN001"
        assert common.model_type == "GARDENA smart Sensor"
        assert common.battery_level == 85
        assert common.battery_state == "OK"
        assert common.rf_link_level == 60
        assert common.rf_link_state == "ONLINE"

    def test_sensor_service_fields(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        sensor = devices[SENSOR_DEVICE_ID].sensor
        assert isinstance(sensor, SensorService)
        assert sensor.soil_humidity == 42
        assert sensor.soil_temperature == 18.5
        assert sensor.ambient_temperature == 22.1
        assert sensor.light_intensity == 15000

    def test_device_is_online(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        assert devices[SENSOR_DEVICE_ID].is_online is True

    def test_device_name_from_common(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        assert devices[SENSOR_DEVICE_ID].name == "My Sensor"

    def test_device_serial_from_common(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        assert devices[SENSOR_DEVICE_ID].serial == "SN001"

    def test_sensor_has_no_valve(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        assert not devices[SENSOR_DEVICE_ID].valves
        assert devices[SENSOR_DEVICE_ID].mower is None


class TestWaterControlParsing:
    def test_water_control_parsed(self) -> None:
        devices = _parse_devices(WATER_CONTROL_LOCATION_RESPONSE, LOCATION_ID)
        assert WATER_CONTROL_DEVICE_ID in devices

    def test_has_valve_set(self) -> None:
        devices = _parse_devices(WATER_CONTROL_LOCATION_RESPONSE, LOCATION_ID)
        assert isinstance(devices[WATER_CONTROL_DEVICE_ID].valve_set, ValveSetService)

    def test_has_one_valve(self) -> None:
        devices = _parse_devices(WATER_CONTROL_LOCATION_RESPONSE, LOCATION_ID)
        assert len(devices[WATER_CONTROL_DEVICE_ID].valves) == 1

    def test_valve_service_id(self) -> None:
        devices = _parse_devices(WATER_CONTROL_LOCATION_RESPONSE, LOCATION_ID)
        valve_ids = list(devices[WATER_CONTROL_DEVICE_ID].valves.keys())
        assert valve_ids[0] == f"{WATER_CONTROL_DEVICE_ID}:1"

    def test_valve_fields(self) -> None:
        devices = _parse_devices(WATER_CONTROL_LOCATION_RESPONSE, LOCATION_ID)
        valve = devices[WATER_CONTROL_DEVICE_ID].valves[f"{WATER_CONTROL_DEVICE_ID}:1"]
        assert isinstance(valve, ValveService)
        assert valve.name == "My Valve"
        assert valve.activity == "CLOSED"
        assert valve.state == "OK"
        assert valve.device_id == WATER_CONTROL_DEVICE_ID

    def test_valve_device_id_stripped_of_suffix(self) -> None:
        devices = _parse_devices(WATER_CONTROL_LOCATION_RESPONSE, LOCATION_ID)
        valve = devices[WATER_CONTROL_DEVICE_ID].valves[f"{WATER_CONTROL_DEVICE_ID}:1"]
        assert ":" not in valve.device_id


class TestIrrigationControlParsing:
    def test_six_valves_parsed(self) -> None:
        devices = _parse_devices(IRRIGATION_LOCATION_RESPONSE, LOCATION_ID)
        assert len(devices[IRRIGATION_DEVICE_ID].valves) == 6

    def test_valve_ids_indexed_one_to_six(self) -> None:
        devices = _parse_devices(IRRIGATION_LOCATION_RESPONSE, LOCATION_ID)
        for i in range(1, 7):
            assert f"{IRRIGATION_DEVICE_ID}:{i}" in devices[IRRIGATION_DEVICE_ID].valves

    def test_valve_names(self) -> None:
        devices = _parse_devices(IRRIGATION_LOCATION_RESPONSE, LOCATION_ID)
        for i in range(1, 7):
            valve = devices[IRRIGATION_DEVICE_ID].valves[f"{IRRIGATION_DEVICE_ID}:{i}"]
            assert valve.name == f"Zone {i}"


class TestPowerSocketParsing:
    def test_power_socket_parsed(self) -> None:
        devices = _parse_devices(POWER_SOCKET_LOCATION_RESPONSE, LOCATION_ID)
        ps = devices[POWER_SOCKET_DEVICE_ID].power_socket
        assert isinstance(ps, PowerSocketService)
        assert ps.activity == "OFF"
        assert ps.state == "OK"

    def test_power_socket_no_battery(self) -> None:
        devices = _parse_devices(POWER_SOCKET_LOCATION_RESPONSE, LOCATION_ID)
        common = devices[POWER_SOCKET_DEVICE_ID].common
        assert common is not None
        assert common.battery_level is None


class TestDeviceOffline:
    def test_offline_device(self) -> None:
        response = {
            **SENSOR_LOCATION_RESPONSE,
            "included": [
                item if item.get("type") != "COMMON"
                else {
                    **item,
                    "attributes": {
                        **item["attributes"],
                        "rfLinkState": {"value": "OFFLINE"},
                    },
                }
                for item in SENSOR_LOCATION_RESPONSE["included"]
            ],
        }
        devices = _parse_devices(response, LOCATION_ID)
        assert devices[SENSOR_DEVICE_ID].is_online is False

    def test_device_without_common_is_offline(self) -> None:
        device = Device(device_id="x", location_id=LOCATION_ID)
        assert device.is_online is False

    def test_device_without_common_has_empty_name(self) -> None:
        device = Device(device_id="x", location_id=LOCATION_ID)
        assert device.name == "x"  # falls back to device_id
        assert device.serial == ""
        assert device.model == ""


class TestServiceUpdates:
    def test_common_service_update(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        common = devices[SENSOR_DEVICE_ID].common
        assert common is not None

        common.update_from_api({
            "attributes": {
                "batteryLevel": {"value": 50},
                "rfLinkState": {"value": "OFFLINE"},
            }
        })
        assert common.battery_level == 50
        assert common.rf_link_state == "OFFLINE"

    def test_common_service_partial_update_keeps_existing(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        common = devices[SENSOR_DEVICE_ID].common
        assert common is not None
        original_name = common.name

        common.update_from_api({"attributes": {"batteryLevel": {"value": 10}}})
        assert common.name == original_name  # unchanged

    def test_sensor_service_update(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        sensor = devices[SENSOR_DEVICE_ID].sensor
        assert sensor is not None

        sensor.update_from_api({
            "attributes": {
                "soilHumidity": {"value": 75},
                "soilTemperature": {"value": 20.0},
            }
        })
        assert sensor.soil_humidity == 75
        assert sensor.soil_temperature == 20.0

    def test_valve_service_update(self) -> None:
        devices = _parse_devices(WATER_CONTROL_LOCATION_RESPONSE, LOCATION_ID)
        valve = devices[WATER_CONTROL_DEVICE_ID].valves[f"{WATER_CONTROL_DEVICE_ID}:1"]

        valve.update_from_api({
            "attributes": {
                "activity": {"value": "MANUAL_WATERING"},
                "duration": {"value": 3600},
            }
        })
        assert valve.activity == "MANUAL_WATERING"
        assert valve.duration == 3600

    def test_valve_set_service_update(self) -> None:
        devices = _parse_devices(WATER_CONTROL_LOCATION_RESPONSE, LOCATION_ID)
        valve_set = devices[WATER_CONTROL_DEVICE_ID].valve_set
        assert valve_set is not None

        valve_set.update_from_api({
            "attributes": {"state": {"value": "WARNING"}}
        })
        assert valve_set.state == "WARNING"

    def test_power_socket_update(self) -> None:
        devices = _parse_devices(POWER_SOCKET_LOCATION_RESPONSE, LOCATION_ID)
        ps = devices[POWER_SOCKET_DEVICE_ID].power_socket
        assert ps is not None

        ps.update_from_api({
            "attributes": {"activity": {"value": "FOREVER_ON"}}
        })
        assert ps.activity == "FOREVER_ON"
