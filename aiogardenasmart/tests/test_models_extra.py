"""Additional model tests to increase coverage of mower service and update paths."""

from __future__ import annotations

from aiogardenasmart.client import _parse_devices
from aiogardenasmart.models import MowerService

from .fixtures import (
    LOCATION_ID,
    MOWER_DEVICE_ID,
    MOWER_LOCATION_RESPONSE,
    SENSOR_DEVICE_ID,
    SENSOR_LOCATION_RESPONSE,
    SERVICE_BEFORE_DEVICE_RESPONSE,
    WATER_CONTROL_DEVICE_ID,
    WATER_CONTROL_LOCATION_RESPONSE,
)


class TestMowerDeviceParsing:
    def test_mower_device_parsed(self) -> None:
        devices = _parse_devices(MOWER_LOCATION_RESPONSE, LOCATION_ID)
        assert MOWER_DEVICE_ID in devices

    def test_mower_service_fields(self) -> None:
        devices = _parse_devices(MOWER_LOCATION_RESPONSE, LOCATION_ID)
        mower = devices[MOWER_DEVICE_ID].mower
        assert isinstance(mower, MowerService)
        assert mower.activity == "PARKED_PARK_SELECTED"
        assert mower.state == "OK"
        assert mower.operating_hours == 123
        assert mower.last_error_code == "NO_MESSAGE"

    def test_mower_service_id(self) -> None:
        devices = _parse_devices(MOWER_LOCATION_RESPONSE, LOCATION_ID)
        mower = devices[MOWER_DEVICE_ID].mower
        assert mower is not None
        assert mower.service_id == MOWER_DEVICE_ID

    def test_mower_device_id(self) -> None:
        devices = _parse_devices(MOWER_LOCATION_RESPONSE, LOCATION_ID)
        mower = devices[MOWER_DEVICE_ID].mower
        assert mower is not None
        assert mower.device_id == MOWER_DEVICE_ID

    def test_mower_service_update_all_fields(self) -> None:
        devices = _parse_devices(MOWER_LOCATION_RESPONSE, LOCATION_ID)
        mower = devices[MOWER_DEVICE_ID].mower
        assert mower is not None

        mower.update_from_api(
            {
                "attributes": {
                    "activity": {"value": "OK_CUTTING"},
                    "state": {"value": "OK"},
                    "lastErrorCode": {"value": "LIFTED"},
                    "operatingHours": {"value": 200},
                }
            }
        )
        assert mower.activity == "OK_CUTTING"
        assert mower.state == "OK"
        assert mower.last_error_code == "LIFTED"
        assert mower.operating_hours == 200

    def test_mower_service_partial_update(self) -> None:
        devices = _parse_devices(MOWER_LOCATION_RESPONSE, LOCATION_ID)
        mower = devices[MOWER_DEVICE_ID].mower
        assert mower is not None
        original_operating_hours = mower.operating_hours

        mower.update_from_api({"attributes": {"activity": {"value": "OK_SEARCHING"}}})
        assert mower.activity == "OK_SEARCHING"
        assert mower.operating_hours == original_operating_hours  # unchanged


class TestCommonServiceUpdateCoverage:
    """Test all branches of CommonService.update_from_api."""

    def test_update_name(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        common = devices[SENSOR_DEVICE_ID].common
        assert common is not None

        common.update_from_api({"attributes": {"name": {"value": "Renamed"}}})
        assert common.name == "Renamed"

    def test_update_battery_level(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        common = devices[SENSOR_DEVICE_ID].common
        assert common is not None

        common.update_from_api({"attributes": {"batteryLevel": {"value": 5}}})
        assert common.battery_level == 5

    def test_update_rf_link_level(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        common = devices[SENSOR_DEVICE_ID].common
        assert common is not None

        common.update_from_api({"attributes": {"rfLinkLevel": {"value": 30}}})
        assert common.rf_link_level == 30

    def test_update_rf_link_state_offline(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        common = devices[SENSOR_DEVICE_ID].common
        assert common is not None

        common.update_from_api({"attributes": {"rfLinkState": {"value": "OFFLINE"}}})
        assert common.rf_link_state == "OFFLINE"


class TestValveServiceUpdateCoverage:
    """Test all branches of ValveService.update_from_api."""

    def test_update_name(self) -> None:
        devices = _parse_devices(WATER_CONTROL_LOCATION_RESPONSE, LOCATION_ID)
        valve = devices[WATER_CONTROL_DEVICE_ID].valves[f"{WATER_CONTROL_DEVICE_ID}:1"]

        valve.update_from_api({"attributes": {"name": {"value": "Renamed Valve"}}})
        assert valve.name == "Renamed Valve"

    def test_update_state(self) -> None:
        devices = _parse_devices(WATER_CONTROL_LOCATION_RESPONSE, LOCATION_ID)
        valve = devices[WATER_CONTROL_DEVICE_ID].valves[f"{WATER_CONTROL_DEVICE_ID}:1"]

        valve.update_from_api({"attributes": {"state": {"value": "ERROR"}}})
        assert valve.state == "ERROR"

    def test_update_last_error_code(self) -> None:
        devices = _parse_devices(WATER_CONTROL_LOCATION_RESPONSE, LOCATION_ID)
        valve = devices[WATER_CONTROL_DEVICE_ID].valves[f"{WATER_CONTROL_DEVICE_ID}:1"]

        valve.update_from_api({"attributes": {"lastErrorCode": {"value": "VOLTAGE_DROP"}}})
        assert valve.last_error_code == "VOLTAGE_DROP"


class TestSensorServiceUpdateCoverage:
    """Test ambient temperature and light intensity update paths."""

    def test_update_ambient_temperature(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        sensor = devices[SENSOR_DEVICE_ID].sensor
        assert sensor is not None

        sensor.update_from_api({"attributes": {"ambientTemperature": {"value": 30.0}}})
        assert sensor.ambient_temperature == 30.0

    def test_update_light_intensity(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        sensor = devices[SENSOR_DEVICE_ID].sensor
        assert sensor is not None

        sensor.update_from_api({"attributes": {"lightIntensity": {"value": 50000}}})
        assert sensor.light_intensity == 50000


class TestPowerSocketUpdateCoverage:
    """Test all PowerSocketService.update_from_api branches."""

    def _get_power_socket(self):  # type: ignore[no-untyped-def]
        from .fixtures import POWER_SOCKET_DEVICE_ID, POWER_SOCKET_LOCATION_RESPONSE

        devices = _parse_devices(POWER_SOCKET_LOCATION_RESPONSE, LOCATION_ID)
        return devices[POWER_SOCKET_DEVICE_ID].power_socket

    def test_update_state(self) -> None:
        ps = self._get_power_socket()
        assert ps is not None
        ps.update_from_api({"attributes": {"state": {"value": "WARNING"}}})
        assert ps.state == "WARNING"

    def test_update_duration(self) -> None:
        ps = self._get_power_socket()
        assert ps is not None
        ps.update_from_api({"attributes": {"duration": {"value": 3600}}})
        assert ps.duration == 3600

    def test_update_last_error_code(self) -> None:
        ps = self._get_power_socket()
        assert ps is not None
        ps.update_from_api({"attributes": {"lastErrorCode": {"value": "TIMER_CANCELLED"}}})
        assert ps.last_error_code == "TIMER_CANCELLED"


class TestServiceBeforeDeviceEntry:
    """Test that _parse_devices handles services appearing before their DEVICE entry."""

    def test_device_created_from_service_before_device_entry(self) -> None:
        devices = _parse_devices(SERVICE_BEFORE_DEVICE_RESPONSE, LOCATION_ID)
        assert SENSOR_DEVICE_ID in devices
        assert devices[SENSOR_DEVICE_ID].common is not None
        assert devices[SENSOR_DEVICE_ID].common.name == "Early Sensor"


class TestDevicePropertiesCoverage:
    def test_device_model_from_common(self) -> None:
        devices = _parse_devices(MOWER_LOCATION_RESPONSE, LOCATION_ID)
        assert devices[MOWER_DEVICE_ID].model == "GARDENA smart Mower"

    def test_valve_set_update_last_error_code(self) -> None:
        devices = _parse_devices(WATER_CONTROL_LOCATION_RESPONSE, LOCATION_ID)
        valve_set = devices[WATER_CONTROL_DEVICE_ID].valve_set
        assert valve_set is not None
        valve_set.update_from_api({"attributes": {"lastErrorCode": {"value": "BUTTON_PRESS"}}})
        assert valve_set.last_error_code == "BUTTON_PRESS"

    def test_common_update_battery_state(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        common = devices[SENSOR_DEVICE_ID].common
        assert common is not None
        common.update_from_api({"attributes": {"batteryState": {"value": "LOW"}}})
        assert common.battery_state == "LOW"
