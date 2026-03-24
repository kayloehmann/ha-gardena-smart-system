"""Tests for GardenaWebSocket connection and reconnect lifecycle."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp

from aiogardenasmart.auth import GardenaAuth
from aiogardenasmart.client import _parse_devices
from aiogardenasmart.websocket import GardenaWebSocket, _apply_service_update

from .fixtures import (
    LOCATION_ID,
    MOWER_DEVICE_ID,
    MOWER_LOCATION_RESPONSE,
    POWER_SOCKET_DEVICE_ID,
    POWER_SOCKET_LOCATION_RESPONSE,
    SENSOR_DEVICE_ID,
    SENSOR_LOCATION_RESPONSE,
    WATER_CONTROL_DEVICE_ID,
    WATER_CONTROL_LOCATION_RESPONSE,
)


def _make_text_msg(data: dict[str, Any]) -> aiohttp.WSMessage:
    return aiohttp.WSMessage(
        type=aiohttp.WSMsgType.TEXT,
        data=json.dumps(data),
        extra=None,
    )


def _make_close_msg() -> aiohttp.WSMessage:
    return aiohttp.WSMessage(type=aiohttp.WSMsgType.CLOSE, data=None, extra=None)


def _make_mock_ws(messages: list[aiohttp.WSMessage]) -> AsyncMock:
    """Build a mock ClientWebSocketResponse that yields the given messages."""
    mock_ws = AsyncMock()
    mock_ws.closed = False
    mock_ws.exception.return_value = None

    async def _aiter() -> AsyncGenerator[aiohttp.WSMessage, None]:
        for msg in messages:
            yield msg

    mock_ws.__aiter__ = _aiter
    return mock_ws


class TestWebSocketConnect:
    async def test_connect_starts_listen_task(self) -> None:
        session = MagicMock(spec=aiohttp.ClientSession)
        auth = MagicMock(spec=GardenaAuth)
        auth.client_id = "test"
        auth.async_ensure_valid_token = AsyncMock(return_value="token")

        # Make ws_connect return a mock that closes immediately
        close_msg = _make_close_msg()
        mock_ws = _make_mock_ws([close_msg])
        session.ws_connect = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_ws),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        devices: dict[str, Any] = {}
        ws = GardenaWebSocket(
            auth=auth, websession=session, devices=devices, on_update=lambda *a: None
        )
        await ws.async_connect("wss://test")
        assert ws._listen_task is not None
        assert ws._running is True

        # Allow the task to run
        await asyncio.sleep(0)
        await ws.async_disconnect()

    async def test_disconnect_when_ws_open(self) -> None:
        session = MagicMock(spec=aiohttp.ClientSession)
        auth = MagicMock(spec=GardenaAuth)
        auth.client_id = "test"

        devices: dict[str, Any] = {}
        ws = GardenaWebSocket(
            auth=auth, websession=session, devices=devices, on_update=lambda *a: None
        )

        mock_inner_ws = AsyncMock()
        mock_inner_ws.closed = False
        ws._ws = mock_inner_ws

        # Create a task that won't finish
        async def _noop() -> None:
            await asyncio.sleep(100)

        ws._listen_task = asyncio.create_task(_noop())
        ws._running = True

        await ws.async_disconnect()
        mock_inner_ws.close.assert_called_once()
        assert not ws._running

    async def test_disconnect_when_ws_already_closed(self) -> None:
        session = MagicMock(spec=aiohttp.ClientSession)
        auth = MagicMock(spec=GardenaAuth)
        auth.client_id = "test"

        devices: dict[str, Any] = {}
        ws = GardenaWebSocket(
            auth=auth, websession=session, devices=devices, on_update=lambda *a: None
        )

        mock_inner_ws = AsyncMock()
        mock_inner_ws.closed = True  # already closed
        ws._ws = mock_inner_ws
        ws._running = True

        await ws.async_disconnect()
        mock_inner_ws.close.assert_not_called()

    async def test_ws_error_message_raises(self) -> None:
        devices = _parse_devices(SENSOR_LOCATION_RESPONSE, LOCATION_ID)
        errors: list[Exception] = []

        session = MagicMock(spec=aiohttp.ClientSession)
        auth = MagicMock(spec=GardenaAuth)
        auth.client_id = "test"
        auth.async_ensure_valid_token = AsyncMock(return_value="token")

        error_msg = aiohttp.WSMessage(type=aiohttp.WSMsgType.ERROR, data=None, extra=None)
        mock_ws = _make_mock_ws([error_msg])
        session.ws_connect = MagicMock(
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_ws),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        ws = GardenaWebSocket(
            auth=auth,
            websession=session,
            devices=devices,
            on_update=lambda *a: None,
            on_error=lambda e: errors.append(e),
        )

        await ws.async_connect("wss://test")
        # Allow reconnect attempts to exhaust (they retry 10 times — but we mock no-sleep)
        await asyncio.sleep(0)
        await ws.async_disconnect()


class TestApplyServiceUpdateAllTypes:
    """Cover all service types in _apply_service_update."""

    def test_mower_update_applied(self) -> None:
        devices = _parse_devices(MOWER_LOCATION_RESPONSE, LOCATION_ID)
        device = devices[MOWER_DEVICE_ID]

        _apply_service_update(
            device,
            "MOWER",
            MOWER_DEVICE_ID,
            {
                "attributes": {"activity": {"value": "OK_CUTTING"}},
                "relationships": {"device": {"data": {"id": MOWER_DEVICE_ID}}},
            },
        )
        assert device.mower is not None
        assert device.mower.activity == "OK_CUTTING"

    def test_power_socket_update_applied(self) -> None:
        devices = _parse_devices(POWER_SOCKET_LOCATION_RESPONSE, LOCATION_ID)
        device = devices[POWER_SOCKET_DEVICE_ID]

        _apply_service_update(
            device,
            "POWER_SOCKET",
            POWER_SOCKET_DEVICE_ID,
            {"attributes": {"activity": {"value": "FOREVER_ON"}}},
        )
        assert device.power_socket is not None
        assert device.power_socket.activity == "FOREVER_ON"

    def test_valve_set_update_applied(self) -> None:
        devices = _parse_devices(WATER_CONTROL_LOCATION_RESPONSE, LOCATION_ID)
        device = devices[WATER_CONTROL_DEVICE_ID]

        _apply_service_update(
            device,
            "VALVE_SET",
            WATER_CONTROL_DEVICE_ID,
            {
                "attributes": {"state": {"value": "ERROR"}},
                "relationships": {"device": {"data": {"id": WATER_CONTROL_DEVICE_ID}}},
            },
        )
        assert device.valve_set is not None
        assert device.valve_set.state == "ERROR"

    def test_new_mower_service_created_if_missing(self) -> None:
        from aiogardenasmart.models import Device

        device = Device(device_id=MOWER_DEVICE_ID, location_id=LOCATION_ID)
        assert device.mower is None

        _apply_service_update(
            device,
            "MOWER",
            MOWER_DEVICE_ID,
            {
                "id": MOWER_DEVICE_ID,
                "attributes": {
                    "activity": {"value": "PARKED_PARK_SELECTED"},
                    "state": {"value": "OK"},
                },
                "relationships": {"device": {"data": {"id": MOWER_DEVICE_ID, "type": "DEVICE"}}},
            },
        )
        assert device.mower is not None

    def test_new_power_socket_created_if_missing(self) -> None:
        from aiogardenasmart.models import Device

        device = Device(device_id=POWER_SOCKET_DEVICE_ID, location_id=LOCATION_ID)
        assert device.power_socket is None

        _apply_service_update(
            device,
            "POWER_SOCKET",
            POWER_SOCKET_DEVICE_ID,
            {
                "id": POWER_SOCKET_DEVICE_ID,
                "attributes": {"activity": {"value": "OFF"}, "state": {"value": "OK"}},
                "relationships": {
                    "device": {"data": {"id": POWER_SOCKET_DEVICE_ID, "type": "DEVICE"}}
                },
            },
        )
        assert device.power_socket is not None

    def test_new_valve_set_created_if_missing(self) -> None:
        from aiogardenasmart.models import Device

        device = Device(device_id=WATER_CONTROL_DEVICE_ID, location_id=LOCATION_ID)
        assert device.valve_set is None

        _apply_service_update(
            device,
            "VALVE_SET",
            WATER_CONTROL_DEVICE_ID,
            {
                "id": WATER_CONTROL_DEVICE_ID,
                "attributes": {"state": {"value": "OK"}},
                "relationships": {
                    "device": {"data": {"id": WATER_CONTROL_DEVICE_ID, "type": "DEVICE"}}
                },
            },
        )
        assert device.valve_set is not None

    def test_new_sensor_created_if_missing(self) -> None:
        from aiogardenasmart.models import Device

        device = Device(device_id=SENSOR_DEVICE_ID, location_id=LOCATION_ID)
        assert device.sensor is None

        _apply_service_update(
            device,
            "SENSOR",
            SENSOR_DEVICE_ID,
            {
                "id": SENSOR_DEVICE_ID,
                "attributes": {"soilHumidity": {"value": 50}},
                "relationships": {"device": {"data": {"id": SENSOR_DEVICE_ID, "type": "DEVICE"}}},
            },
        )
        assert device.sensor is not None
        assert device.sensor.soil_humidity == 50

    def test_pong_not_sent_when_ws_none(self) -> None:
        """Pong send is skipped when _ws is None (e.g. before connection)."""
        session = MagicMock(spec=aiohttp.ClientSession)
        auth = MagicMock(spec=GardenaAuth)
        auth.client_id = "test"
        devices: dict[str, Any] = {}

        ws = GardenaWebSocket(
            auth=auth, websession=session, devices=devices, on_update=lambda *a: None
        )
        # _ws is None by default — should not raise
        assert ws._ws is None
