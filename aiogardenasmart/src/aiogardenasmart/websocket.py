"""WebSocket client for real-time Gardena Smart System device updates."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from typing import Any

import aiohttp

from .auth import GardenaAuth
from .const import (
    AUTHORIZATION_PROVIDER,
    WEBSOCKET_MAX_RECONNECT_ATTEMPTS,
    WEBSOCKET_PING_INTERVAL,
    WEBSOCKET_RECONNECT_BASE_DELAY,
    ServiceType,
)
from .exceptions import GardenaWebSocketError
from .models import (
    CommonService,
    Device,
    MowerService,
    PowerSocketService,
    SensorService,
    ValveService,
    ValveSetService,
)

_LOGGER = logging.getLogger(__name__)

DeviceUpdateCallback = Callable[[str, Device], None]


class GardenaWebSocket:
    """Manages a WebSocket connection to the Gardena Smart System API.

    Receives real-time service state updates and applies them to the
    provided device registry. Calls ``on_update`` for each changed device.

    An ``aiohttp.ClientSession`` must be provided by the caller — this class
    does not create sessions internally (platinum: inject-websession rule).
    """

    def __init__(
        self,
        auth: GardenaAuth,
        websession: aiohttp.ClientSession,
        devices: dict[str, Device],
        on_update: DeviceUpdateCallback,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Initialize the WebSocket client."""
        self._auth = auth
        self._websession = websession
        self._devices = devices
        self._on_update = on_update
        self._on_error = on_error
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._running = False

    async def async_connect(self, ws_url: str) -> None:
        """Establish the WebSocket connection and begin listening.

        Reconnects automatically with exponential backoff on transient errors.
        """
        self._running = True
        self._listen_task = asyncio.create_task(
            self._async_listen_loop(ws_url), name="gardena_ws_listen"
        )

    async def async_disconnect(self) -> None:
        """Close the WebSocket connection and stop listening."""
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task

    async def _async_listen_loop(self, ws_url: str) -> None:
        """Outer loop that reconnects on failure."""
        attempt = 0
        while self._running:
            try:
                await self._async_connect_and_listen(ws_url)
                attempt = 0  # reset on clean exit
            except asyncio.CancelledError:
                break
            except Exception as err:
                if not self._running:
                    break
                attempt += 1
                if attempt > WEBSOCKET_MAX_RECONNECT_ATTEMPTS:
                    _LOGGER.error(
                        "Gardena WebSocket: giving up after %d reconnect attempts",
                        attempt,
                    )
                    if self._on_error:
                        self._on_error(GardenaWebSocketError(f"Max reconnects reached: {err}"))
                    break
                delay = WEBSOCKET_RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
                _LOGGER.warning(
                    "Gardena WebSocket error (attempt %d/%d), reconnecting in %.0fs: %s",
                    attempt,
                    WEBSOCKET_MAX_RECONNECT_ATTEMPTS,
                    delay,
                    err,
                )
                await asyncio.sleep(delay)

    async def _async_connect_and_listen(self, ws_url: str) -> None:
        """Connect to the WebSocket URL and process messages until closed."""
        token = await self._auth.async_ensure_valid_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Authorization-Provider": AUTHORIZATION_PROVIDER,
            "X-Api-Key": self._auth.client_id,
        }
        async with self._websession.ws_connect(
            ws_url,
            headers=headers,
            heartbeat=WEBSOCKET_PING_INTERVAL,
        ) as ws:
            self._ws = ws
            _LOGGER.debug("Gardena WebSocket connected")
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._async_handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    raise GardenaWebSocketError(f"WebSocket error: {ws.exception()}")
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                ):
                    _LOGGER.debug("Gardena WebSocket closed")
                    break

    async def _async_handle_message(self, raw: str) -> None:
        """Parse and dispatch an incoming WebSocket message."""
        try:
            message: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            _LOGGER.warning("Gardena WebSocket: received non-JSON message: %.200s", raw)
            return

        msg_type: str = str(message.get("type", ""))

        # Handle ping/pong at the application layer
        if msg_type == "WEBSOCKET_PING":
            await self._async_send_pong()
            return

        # Service state update — same structure as the included[] REST objects
        if msg_type not in (
            ServiceType.COMMON,
            ServiceType.MOWER,
            ServiceType.VALVE,
            ServiceType.VALVE_SET,
            ServiceType.SENSOR,
            ServiceType.POWER_SOCKET,
        ):
            _LOGGER.debug("Gardena WebSocket: ignoring message type %s", msg_type)
            return

        service_type: str = msg_type
        item_id: str = str(message.get("id", ""))
        base_device_id = item_id.split(":")[0]
        device = self._devices.get(base_device_id)
        if device is None:
            _LOGGER.debug(
                "Gardena WebSocket: received update for unknown device %s", base_device_id
            )
            return

        try:
            _apply_service_update(device, service_type, item_id, message)
        except Exception:
            _LOGGER.exception(
                "Gardena WebSocket: error processing update for device %s", base_device_id
            )
            return
        self._on_update(base_device_id, device)

    async def _async_send_pong(self) -> None:
        """Respond to a server ping with a pong."""
        if self._ws and not self._ws.closed:
            pong = json.dumps({"data": {"type": "WEBSOCKET_PONG", "attributes": {}}})
            await self._ws.send_str(pong)


def _apply_service_update(
    device: Device,
    service_type: str,
    item_id: str,
    data: dict[str, Any],
) -> None:
    """Apply an incoming service update to the appropriate service on the device."""
    if service_type == ServiceType.COMMON:
        if device.common:
            device.common.update_from_api(data)
        else:
            device.common = CommonService.from_api(data)

    elif service_type == ServiceType.MOWER:
        if device.mower:
            device.mower.update_from_api(data)
        else:
            device.mower = MowerService.from_api(data)

    elif service_type == ServiceType.VALVE:
        if item_id in device.valves:
            device.valves[item_id].update_from_api(data)
        else:
            device.valves[item_id] = ValveService.from_api(data)

    elif service_type == ServiceType.VALVE_SET:
        if device.valve_set:
            device.valve_set.update_from_api(data)
        else:
            device.valve_set = ValveSetService.from_api(data)

    elif service_type == ServiceType.SENSOR:
        if device.sensor:
            device.sensor.update_from_api(data)
        else:
            device.sensor = SensorService.from_api(data)

    elif service_type == ServiceType.POWER_SOCKET:
        if device.power_socket:
            device.power_socket.update_from_api(data)
        else:
            device.power_socket = PowerSocketService.from_api(data)
