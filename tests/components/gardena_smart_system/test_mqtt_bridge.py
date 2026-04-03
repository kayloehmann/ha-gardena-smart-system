"""Tests for the MQTT bridge (mqtt_bridge.py)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.gardena_smart_system.mqtt_bridge import (
    MqttBridge,
    _is_mqtt_available,
    _serialize_device,
)

from .conftest import make_mock_device


class TestSerializeDevice:
    """Test device serialization to JSON-safe dict."""

    def test_serialize_sensor_device(self) -> None:
        device = make_mock_device()
        data = _serialize_device(device)

        assert data["device_id"] == "device-uuid"
        assert data["name"] == "My Sensor"
        assert data["is_online"] is True
        assert data["common"]["battery_level"] == 85
        assert data["sensor"]["soil_humidity"] == 42
        assert data["sensor"]["soil_temperature"] == 18.5

    def test_serialize_valve_device(self) -> None:
        device = make_mock_device(valve_count=2)
        data = _serialize_device(device)

        assert len(data["valves"]) == 2
        assert data["valves"]["device-uuid:1"]["activity"] == "CLOSED"
        assert data["valves"]["device-uuid:1"]["name"] == "Valve 1"

    def test_serialize_mower_device(self) -> None:
        device = make_mock_device(has_mower=True, has_sensor=False)
        data = _serialize_device(device)

        assert data["mower"]["activity"] == "PARKED_PARK_SELECTED"
        assert data["mower"]["operating_hours"] == 100

    def test_serialize_power_socket_device(self) -> None:
        device = make_mock_device(has_power_socket=True)
        data = _serialize_device(device)

        assert data["power_socket"]["activity"] == "OFF"

    def test_serialize_single_valve(self) -> None:
        device = make_mock_device(single_valve=True)
        data = _serialize_device(device)

        assert len(data["valves"]) == 1
        assert "device-uuid" in data["valves"]

    def test_serialized_data_is_json_safe(self) -> None:
        device = make_mock_device(valve_count=1, has_mower=True, has_power_socket=True)
        data = _serialize_device(device)
        # Should not raise
        result = json.dumps(data, default=str)
        assert isinstance(result, str)


class TestMqttAvailability:
    """Test MQTT availability detection."""

    def test_mqtt_not_available(self, hass: HomeAssistant) -> None:
        assert _is_mqtt_available(hass) is False

    def test_mqtt_available(self, hass: HomeAssistant) -> None:
        hass.config.components.add("mqtt")
        assert _is_mqtt_available(hass) is True


class TestMqttBridgeLifecycle:
    """Test MQTT bridge start/stop lifecycle."""

    async def test_bridge_not_started_without_mqtt(self, hass: HomeAssistant) -> None:
        bridge = MqttBridge(hass, "gardena")
        result = await bridge.async_start()
        assert result is False
        assert bridge.is_active is False

    async def test_bridge_starts_with_mqtt(self, hass: HomeAssistant) -> None:
        hass.config.components.add("mqtt")
        bridge = MqttBridge(hass, "test/gardena")

        with patch("custom_components.gardena_smart_system.mqtt_bridge.mqtt") as mock_mqtt:
            mock_mqtt.async_subscribe = AsyncMock()
            result = await bridge.async_start(command_handler=AsyncMock())

        assert result is True
        assert bridge.is_active is True

    async def test_bridge_stop(self, hass: HomeAssistant) -> None:
        hass.config.components.add("mqtt")
        bridge = MqttBridge(hass, "gardena")
        unsub = MagicMock()

        with patch("custom_components.gardena_smart_system.mqtt_bridge.mqtt") as mock_mqtt:
            mock_mqtt.async_subscribe = AsyncMock(return_value=unsub)
            await bridge.async_start(command_handler=AsyncMock())

        await bridge.async_stop()
        assert bridge.is_active is False
        unsub.assert_called_once()


class TestMqttBridgePublish:
    """Test MQTT state publishing."""

    async def test_publish_device_state(self, hass: HomeAssistant) -> None:
        hass.config.components.add("mqtt")
        bridge = MqttBridge(hass, "gardena", subscribe_commands=False)

        with patch("custom_components.gardena_smart_system.mqtt_bridge.mqtt") as mock_mqtt:
            mock_mqtt.async_publish = AsyncMock()
            await bridge.async_start()

            device = make_mock_device()
            await bridge.async_publish_device_state("dev-1", device)

            mock_mqtt.async_publish.assert_called_once()
            call_args = mock_mqtt.async_publish.call_args
            assert call_args[0][1] == "gardena/dev-1/state"
            payload = json.loads(call_args[0][2])
            assert payload["device_id"] == "device-uuid"

    async def test_publish_availability(self, hass: HomeAssistant) -> None:
        hass.config.components.add("mqtt")
        bridge = MqttBridge(hass, "gardena", subscribe_commands=False)

        with patch("custom_components.gardena_smart_system.mqtt_bridge.mqtt") as mock_mqtt:
            mock_mqtt.async_publish = AsyncMock()
            await bridge.async_start()

            await bridge.async_publish_availability("dev-1", True)
            call_args = mock_mqtt.async_publish.call_args
            assert call_args[0][1] == "gardena/dev-1/availability"
            assert call_args[0][2] == "online"

            await bridge.async_publish_availability("dev-1", False)
            call_args = mock_mqtt.async_publish.call_args
            assert call_args[0][2] == "offline"

    async def test_publish_all_devices(self, hass: HomeAssistant) -> None:
        hass.config.components.add("mqtt")
        bridge = MqttBridge(hass, "gardena", subscribe_commands=False)

        with patch("custom_components.gardena_smart_system.mqtt_bridge.mqtt") as mock_mqtt:
            mock_mqtt.async_publish = AsyncMock()
            await bridge.async_start()

            dev1 = make_mock_device("d1", "SN1", "Sensor 1")
            dev2 = make_mock_device("d2", "SN2", "Sensor 2")
            await bridge.async_publish_all_devices({"d1": dev1, "d2": dev2})

            # 2 devices × 2 calls each (state + availability) = 4
            assert mock_mqtt.async_publish.call_count == 4

    async def test_no_publish_when_disabled(self, hass: HomeAssistant) -> None:
        hass.config.components.add("mqtt")
        bridge = MqttBridge(hass, "gardena", publish_states=False, subscribe_commands=False)

        with patch("custom_components.gardena_smart_system.mqtt_bridge.mqtt") as mock_mqtt:
            mock_mqtt.async_publish = AsyncMock()
            await bridge.async_start()

            device = make_mock_device()
            await bridge.async_publish_device_state("dev-1", device)
            mock_mqtt.async_publish.assert_not_called()

    async def test_no_publish_when_not_started(self, hass: HomeAssistant) -> None:
        bridge = MqttBridge(hass, "gardena")

        with patch("custom_components.gardena_smart_system.mqtt_bridge.mqtt") as mock_mqtt:
            mock_mqtt.async_publish = AsyncMock()
            device = make_mock_device()
            await bridge.async_publish_device_state("dev-1", device)
            mock_mqtt.async_publish.assert_not_called()


class TestMqttBridgeCustomPrefix:
    """Test custom topic prefix."""

    async def test_custom_prefix(self, hass: HomeAssistant) -> None:
        hass.config.components.add("mqtt")
        bridge = MqttBridge(hass, "home/garden", subscribe_commands=False)

        with patch("custom_components.gardena_smart_system.mqtt_bridge.mqtt") as mock_mqtt:
            mock_mqtt.async_publish = AsyncMock()
            await bridge.async_start()

            device = make_mock_device()
            await bridge.async_publish_device_state("dev-1", device)

            topic = mock_mqtt.async_publish.call_args[0][1]
            assert topic == "home/garden/dev-1/state"

    async def test_trailing_slash_stripped(self, hass: HomeAssistant) -> None:
        hass.config.components.add("mqtt")
        bridge = MqttBridge(hass, "gardena/", subscribe_commands=False)

        with patch("custom_components.gardena_smart_system.mqtt_bridge.mqtt") as mock_mqtt:
            mock_mqtt.async_publish = AsyncMock()
            await bridge.async_start()

            device = make_mock_device()
            await bridge.async_publish_device_state("dev-1", device)

            topic = mock_mqtt.async_publish.call_args[0][1]
            assert topic == "gardena/dev-1/state"
