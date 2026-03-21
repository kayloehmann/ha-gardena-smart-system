"""WebSocket client for real-time Husqvarna Automower status updates."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import aiohttp

from aiogardenasmart.auth import GardenaAuth

from .const import (
    AUTHORIZATION_PROVIDER,
    WEBSOCKET_MAX_RECONNECT_ATTEMPTS,
    WEBSOCKET_PING_INTERVAL,
    WEBSOCKET_RECONNECT_BASE_DELAY,
)
from .exceptions import AutomowerWebSocketError
from .models import AutomowerDevice

_LOGGER = logging.getLogger(__name__)

DeviceUpdateCallback = Callable[[str, AutomowerDevice], None]


class AutomowerWebSocket:
    """Manages a WebSocket connection to the Automower Connect API.

    Receives real-time status updates and applies them to the provided
    device registry. Calls ``on_update`` for each changed device.
    """

    def __init__(
        self,
        auth: GardenaAuth,
        websession: aiohttp.ClientSession,
        devices: dict[str, AutomowerDevice],
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
        """Establish the WebSocket connection and begin listening."""
        self._running = True
        self._listen_task = asyncio.create_task(
            self._async_listen_loop(ws_url), name="automower_ws_listen"
        )

    async def async_disconnect(self) -> None:
        """Close the WebSocket connection and stop listening."""
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

    async def _async_listen_loop(self, ws_url: str) -> None:
        """Outer loop that reconnects on failure."""
        attempt = 0
        while self._running:
            try:
                await self._async_connect_and_listen(ws_url)
                attempt = 0
            except asyncio.CancelledError:
                break
            except Exception as err:  # noqa: BLE001
                if not self._running:
                    break
                attempt += 1
                if attempt > WEBSOCKET_MAX_RECONNECT_ATTEMPTS:
                    _LOGGER.error(
                        "Automower WebSocket: giving up after %d reconnect attempts",
                        attempt,
                    )
                    if self._on_error:
                        self._on_error(
                            AutomowerWebSocketError(f"Max reconnects reached: {err}")
                        )
                    break
                delay = WEBSOCKET_RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
                _LOGGER.warning(
                    "Automower WebSocket error (attempt %d/%d), reconnecting in %.0fs: %s",
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
            _LOGGER.debug("Automower WebSocket connected")
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    raise AutomowerWebSocketError(
                        f"WebSocket error: {ws.exception()}"
                    )
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                ):
                    _LOGGER.debug("Automower WebSocket closed")
                    break

    def _handle_message(self, raw: str) -> None:
        """Parse and dispatch an incoming WebSocket message."""
        try:
            message: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            _LOGGER.warning(
                "Automower WebSocket: received non-JSON message: %s", raw
            )
            return

        # The Automower WS sends status updates with mower ID and attributes
        mower_id = message.get("id", "")
        if not mower_id:
            _LOGGER.debug("Automower WebSocket: ignoring message without ID")
            return

        device = self._devices.get(mower_id)
        if device is None:
            _LOGGER.debug(
                "Automower WebSocket: received update for unknown mower %s",
                mower_id,
            )
            return

        device.update_from_api(message)
        self._on_update(mower_id, device)
