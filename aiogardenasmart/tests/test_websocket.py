"""Tests for GardenaWebSocket real-time update handling."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from aiogardenasmart.auth import GardenaAuth
from aiogardenasmart.client import _parse_devices
from aiogardenasmart.websocket import GardenaWebSocket, _apply_service_update

from .fixtures import (
    LOCATION_ID,
    SENSOR_DEVICE_ID,
    SENSOR_LOCATION_RESPONSE,
    TOKEN_RESPONSE,
    WATER_CONTROL_DEVICE_ID,
    WATER_CONTROL_LOCATION_RESPONSE,
)


def _make_ws_message(msg_type: str, data: dict[str, Any]) -> aiohttp.WSMessage:
    """Helper to build a mock WSMessage."""
    payload = json.dumps({**data, "type": msg_type})
    return aiohttp.WSMessage(type=aiohttp.WSMsgType.TEXT, data=payload, extra=None)


def _make_close_message() -> aiohttp.WSMessage:
    return aiohttp.WSMessage(type=aiohttp.WSMsgType.CLOSE, data=None, extra=None)


class TestApplyServiceUpdate:
    def test_common_update_applied(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        device = devices[SENSOR_DEVICE_ID]

        _apply_service_update(
            device,
            "COMMON",
            SENSOR_DEVICE_ID,
            {"attributes": {"batteryLevel": {"value": 20}, "rfLinkState": {"value": "OFFLINE"}}},
        )

        assert device.common is not None
        assert device.common.battery_level == 20
        assert device.common.rf_link_state == "OFFLINE"

    def test_sensor_update_applied(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        device = devices[SENSOR_DEVICE_ID]

        _apply_service_update(
            device,
            "SENSOR",
            SENSOR_DEVICE_ID,
            {"attributes": {"soilHumidity": {"value": 30}}},
        )

        assert device.sensor is not None
        assert device.sensor.soil_humidity == 30

    def test_valve_update_applied(self) -> None:
        devices = _parse_devices(WATER_CONTROL_LOCATION_RESPONSE, LOCATION_ID)
        device = devices[WATER_CONTROL_DEVICE_ID]
        valve_id = f"{WATER_CONTROL_DEVICE_ID}:1"

        _apply_service_update(
            device,
            "VALVE",
            valve_id,
            {"attributes": {"activity": {"value": "MANUAL_WATERING"}, "duration": {"value": 1800}}},
        )

        assert device.valves[valve_id].activity == "MANUAL_WATERING"
        assert device.valves[valve_id].duration == 1800

    def test_new_common_service_created_if_missing(self) -> None:
        from aiogardenasmart.models import Device

        device = Device(device_id="new", location_id=LOCATION_ID)
        assert device.common is None

        _apply_service_update(
            device,
            "COMMON",
            "new",
            {
                "attributes": {
                    "name": {"value": "New"},
                    "serial": {"value": "X"},
                    "modelType": {"value": "Unknown"},
                    "rfLinkState": {"value": "ONLINE"},
                },
                "relationships": {"device": {"data": {"id": "new", "type": "DEVICE"}}},
            },
        )

        assert device.common is not None
        assert device.common.name == "New"


class TestWebSocketMessageHandling:
    @pytest.fixture
    def devices(self) -> dict[str, Any]:
        return _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)

    @pytest.fixture
    def ws(self, devices: dict[str, Any]) -> GardenaWebSocket:
        session = MagicMock(spec=aiohttp.ClientSession)
        auth = MagicMock(spec=GardenaAuth)
        auth.client_id = "test-client"
        return GardenaWebSocket(
            auth=auth,
            websession=session,
            devices=devices,
            on_update=lambda device_id, device: None,
        )

    async def test_sensor_ws_update_triggers_callback(
        self, devices: dict[str, Any]
    ) -> None:
        updated_ids: list[str] = []

        session = MagicMock(spec=aiohttp.ClientSession)
        auth = MagicMock(spec=GardenaAuth)
        auth.client_id = "test-client"

        ws = GardenaWebSocket(
            auth=auth,
            websession=session,
            devices=devices,
            on_update=lambda did, _: updated_ids.append(did),
        )

        msg = json.dumps({
            "id": SENSOR_DEVICE_ID,
            "type": "SENSOR",
            "attributes": {"soilHumidity": {"value": 99}},
        })
        await ws._async_handle_message(msg)

        assert SENSOR_DEVICE_ID in updated_ids
        assert devices[SENSOR_DEVICE_ID].sensor is not None
        assert devices[SENSOR_DEVICE_ID].sensor.soil_humidity == 99

    async def test_ping_sends_pong(self, ws: GardenaWebSocket) -> None:
        mock_ws = AsyncMock()
        mock_ws.closed = False
        ws._ws = mock_ws

        ping_msg = json.dumps({"type": "WEBSOCKET_PING"})
        await ws._async_handle_message(ping_msg)

        mock_ws.send_str.assert_called_once()
        sent = json.loads(mock_ws.send_str.call_args[0][0])
        assert sent["data"]["type"] == "WEBSOCKET_PONG"

    async def test_unknown_type_ignored(self, ws: GardenaWebSocket) -> None:
        msg = json.dumps({"type": "UNKNOWN_TYPE", "id": "x"})
        # Should not raise
        await ws._async_handle_message(msg)

    async def test_invalid_json_ignored(self, ws: GardenaWebSocket) -> None:
        # Should not raise
        await ws._async_handle_message("not json {{{")

    async def test_unknown_device_id_ignored(self, ws: GardenaWebSocket) -> None:
        msg = json.dumps({
            "id": "nonexistent-device-id",
            "type": "SENSOR",
            "attributes": {"soilHumidity": {"value": 10}},
        })
        # Should not raise
        await ws._async_handle_message(msg)

    async def test_common_update_dispatched(
        self, devices: dict[str, Any]
    ) -> None:
        updated: list[str] = []

        session = MagicMock(spec=aiohttp.ClientSession)
        auth = MagicMock(spec=GardenaAuth)
        auth.client_id = "test-client"

        ws = GardenaWebSocket(
            auth=auth,
            websession=session,
            devices=devices,
            on_update=lambda did, _: updated.append(did),
        )

        msg = json.dumps({
            "id": SENSOR_DEVICE_ID,
            "type": "COMMON",
            "attributes": {"rfLinkState": {"value": "OFFLINE"}},
            "relationships": {"device": {"data": {"id": SENSOR_DEVICE_ID}}},
        })
        await ws._async_handle_message(msg)

        assert SENSOR_DEVICE_ID in updated


class TestWebSocketLifecycle:
    async def test_disconnect_cancels_task(self) -> None:
        session = MagicMock(spec=aiohttp.ClientSession)
        auth = MagicMock(spec=GardenaAuth)
        auth.client_id = "test"
        auth.async_ensure_valid_token = AsyncMock(return_value="token")

        devices: dict[str, Any] = {}
        ws = GardenaWebSocket(
            auth=auth,
            websession=session,
            devices=devices,
            on_update=lambda *a: None,
        )

        # Create a task that stays pending
        async def _pending() -> None:
            await asyncio.sleep(100)

        ws._listen_task = asyncio.create_task(_pending())
        ws._running = True

        await ws.async_disconnect()

        assert not ws._running
        assert ws._listen_task.done()
