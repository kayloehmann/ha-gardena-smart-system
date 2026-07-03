"""Local WebSocket channel to the GARDENA smart Gateway.

The official ``gardena-smart-local-api`` is a protocol/model library, not a
transport: it parses/builds frames and models devices, but the WebSocket
connection itself is the consumer's responsibility. This module is that
transport, adapted to Home Assistant conventions and this integration's needs:

* Connects over the **shared HA aiohttp session** (``async_get_clientsession``)
  so the Platinum ``inject-websession`` rule holds for the local path too.
* Self-signed gateway certificate → HA's ``get_default_no_verify_context``.
* **No application-level pings.** The reference client uses ``heartbeat=30``,
  but this gateway firmware (10.4.4) answers WS PING control frames with a
  ``Received non-text data`` error frame (verified live), so we disable
  heartbeat and use a lightweight text ``read`` keepalive instead.
* Cheap LAN reconnects (``LOCAL_RECONNECT_SCHEDULE``) — unlike the cloud WS,
  a local reconnect costs no API budget.

The channel owns the connection and the local ``DeviceMap`` and calls back into
its owner (the Gardena coordinator) on every state change and connection-state
change; translating local device state onto the cloud device model is the
owner's job, not this module's.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
from collections.abc import Callable
from ssl import SSLContext
from typing import Any

import aiohttp
from gardena_smart_local_api.devices import (
    DeviceMap,
    build_discovery_obj,
    create_devices_from_messages,
)
from gardena_smart_local_api.messages import (
    EgressMessageList,
    ErrorMessage,
    Event,
    IngressMessageList,
    Reply,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util.ssl import get_default_no_verify_context

from .const import (
    DEFAULT_LOCAL_PORT,
    LOCAL_COMMAND_ACK_TIMEOUT_SECONDS,
    LOCAL_RECONNECT_SCHEDULE,
)

_LOGGER = logging.getLogger(__name__)

DISCOVERY_TIMEOUT_SECONDS = 30.0
# Keepalive cadence: a quiet garden sends no events, so we periodically read a
# cheap resource to prove the link is alive (and detect a silently-dead socket).
KEEPALIVE_INTERVAL_SECONDS = 60.0


class GardenaLocalChannel:
    """Owns the local gateway WebSocket connection and device state."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        password: str,
        port: int = DEFAULT_LOCAL_PORT,
        *,
        on_devices_updated: Callable[[DeviceMap], None],
        on_connection_change: Callable[[bool], None],
    ) -> None:
        """Initialise the channel; ``async_start`` opens the connection."""
        self._hass = hass
        self._host = host
        self._port = port
        self._uri = f"wss://{host}:{port}"
        self._auth = base64.b64encode(f"_:{password}".encode()).decode("ascii")
        self._on_devices_updated = on_devices_updated
        self._on_connection_change = on_connection_change

        self._session = async_get_clientsession(hass)
        self._ssl: SSLContext | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._runner: asyncio.Task[None] | None = None
        self._connected = False
        self.devices: DeviceMap = DeviceMap({})
        # request_id -> future resolved with the matching Reply
        self._pending: dict[str, asyncio.Future[Reply]] = {}

    # ── public API ────────────────────────────────────────────────
    @property
    def connected(self) -> bool:
        """Whether the local gateway link is currently up."""
        return self._connected

    async def async_start(self) -> None:
        """Start the background connect/reconnect loop (idempotent)."""
        if self._runner is None or self._runner.done():
            # Building the SSL context loads CA files (blocking); do it in the
            # executor per HA guidance rather than on the event loop.
            if self._ssl is None:
                self._ssl = await self._hass.async_add_executor_job(get_default_no_verify_context)
            self._runner = self._hass.async_create_background_task(
                self._run(), "gardena_ng_local_channel"
            )

    async def async_stop(self) -> None:
        """Stop the channel and drop the connection."""
        runner, self._runner = self._runner, None
        if runner is not None:
            runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner
        self._set_connected(False)

    async def async_send_command(self, request: EgressMessageList) -> bool:
        """Send a command and await its acknowledgement.

        Returns ``True`` only if every request in ``request`` is acknowledged
        with ``success`` within ``LOCAL_COMMAND_ACK_TIMEOUT_SECONDS``. Any
        failure (no connection, timeout, error reply) returns ``False`` so the
        caller can fall back to the cloud command path.
        """
        ws = self._ws
        if ws is None or ws.closed:
            return False
        request_ids = [r.request_id for r in request.root if r.request_id is not None]
        if not request_ids:
            return False
        loop = asyncio.get_running_loop()
        futures: dict[str, asyncio.Future[Reply]] = {
            rid: loop.create_future() for rid in request_ids
        }
        self._pending.update(futures)
        try:
            await ws.send_str(request.model_dump_json())
            async with asyncio.timeout(LOCAL_COMMAND_ACK_TIMEOUT_SECONDS):
                replies = await asyncio.gather(*futures.values())
        except (TimeoutError, aiohttp.ClientError, RuntimeError) as err:
            _LOGGER.debug("Local command failed (%s), cloud fallback applies", err)
            return False
        finally:
            for rid in request_ids:
                self._pending.pop(rid, None)
        return all(bool(reply.success) for reply in replies)

    # ── connection loop ───────────────────────────────────────────
    async def _run(self) -> None:
        attempt = 0
        while True:
            try:
                await self._session_once()
                attempt = 0  # a clean session resets the backoff ladder
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.debug("Local gateway connection error: %s", err)
            finally:
                self._set_connected(False)
                self._fail_pending()
            delay = LOCAL_RECONNECT_SCHEDULE[min(attempt, len(LOCAL_RECONNECT_SCHEDULE) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    async def _session_once(self) -> None:
        """One connection lifetime: connect, discover, pump events until close."""
        ssl_ctx = self._ssl
        if ssl_ctx is None:  # async_start sets it first; narrow for the type checker
            ssl_ctx = await self._hass.async_add_executor_job(get_default_no_verify_context)
            self._ssl = ssl_ctx
        async with self._session.ws_connect(
            self._uri,
            ssl=ssl_ctx,
            heartbeat=None,  # firmware rejects WS pings — see module docstring
            autoping=False,
            headers={"Authorization": f"Basic {self._auth}"},
        ) as ws:
            self._ws = ws
            _LOGGER.info("Connected to GARDENA smart Gateway at %s", self._uri)
            # The reader must run concurrently with discovery: discovery awaits
            # reply frames that only the reader can process.
            reader = self._hass.async_create_background_task(
                self._read_loop(ws), "gardena_ng_local_reader"
            )
            keepalive: asyncio.Task[None] | None = None
            try:
                await self._discover(ws)
                self._set_connected(True)
                keepalive = self._hass.async_create_background_task(
                    self._keepalive(ws), "gardena_ng_local_keepalive"
                )
                await reader  # pump until the socket closes or errors
            finally:
                for task in (reader, keepalive):
                    if task is not None:
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
                self._ws = None

    async def _discover(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        request = build_discovery_obj()
        request_ids = [r.request_id for r in request.root if r.request_id is not None]
        loop = asyncio.get_running_loop()
        futures = {rid: loop.create_future() for rid in request_ids}
        self._pending.update(futures)
        await ws.send_str(request.model_dump_json())
        try:
            async with asyncio.timeout(DISCOVERY_TIMEOUT_SECONDS):
                replies = await asyncio.gather(*futures.values())
        finally:
            for rid in request_ids:
                self._pending.pop(rid, None)
        self.devices = await create_devices_from_messages(IngressMessageList(list(replies)))
        _LOGGER.info("Local discovery found %d device(s)", len(self.devices))
        self._on_devices_updated(self.devices)

    async def _read_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type is aiohttp.WSMsgType.TEXT:
                self._on_raw(msg.data)
            elif msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            ):
                break

    async def _keepalive(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Send a cheap text `read` periodically to keep/verify the link."""
        first = next(iter(self.devices.values()), None)
        if first is None:
            return
        probe = first.build_refresh_online_status_obj
        while not ws.closed:
            await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)
            with contextlib.suppress(Exception):
                await ws.send_str(probe.model_dump_json())

    # ── message handling (transport-free, unit-testable) ──────────
    def _on_raw(self, raw: str) -> None:
        try:
            messages = IngressMessageList.model_validate_json(raw)
        except ValueError:
            _LOGGER.debug("Ignoring non-conforming local frame: %s", raw)
            return
        self._handle_ingress(messages)

    def _handle_ingress(self, messages: IngressMessageList) -> None:
        """Resolve pending replies and apply events; notify owner if changed."""
        events: list[Event] = []
        for msg in messages:
            if isinstance(msg, Reply) and msg.request_id in self._pending:
                fut = self._pending.pop(msg.request_id)
                if not fut.done():
                    fut.set_result(msg)
            elif isinstance(msg, ErrorMessage):
                if msg.request_id in self._pending:
                    fut = self._pending.pop(msg.request_id)
                    if not fut.done():
                        fut.set_result(_as_failed_reply(msg))
                else:
                    _LOGGER.debug("Local gateway error frame: %s", msg.error_message)
            elif isinstance(msg, Event):
                events.append(msg)
        if self._apply_events(events):
            self._on_devices_updated(self.devices)

    def _apply_events(self, events: list[Event]) -> bool:
        """Apply update/delete events to the local device map. Returns changed."""
        changed = False
        for event in events:
            device_id = event.entity.device
            if not device_id:
                continue
            if event.op == "delete" and event.entity.path.object_name is None:
                if self.devices.pop(device_id, None) is not None:
                    changed = True
                continue
            device: Any = self.devices.get(device_id)
            if device is None:
                continue
            device.update_data(event)
            changed = True
        return changed

    # ── helpers ───────────────────────────────────────────────────
    @callback
    def _set_connected(self, value: bool) -> None:
        if value != self._connected:
            self._connected = value
            self._on_connection_change(value)

    def _fail_pending(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()


def _as_failed_reply(error: ErrorMessage) -> Reply:
    """Represent an ErrorMessage as an unsuccessful Reply for the waiter."""
    return Reply(request_id=error.request_id or "", success=False, payload=error.payload)
