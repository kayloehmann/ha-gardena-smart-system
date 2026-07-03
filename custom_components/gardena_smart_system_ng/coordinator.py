"""DataUpdateCoordinator for the Gardena Smart System integration."""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from aiogardenasmart import (
    Device,
    GardenaAuth,
    GardenaAuthenticationError,
    GardenaClient,
    GardenaConnectionError,
    GardenaException,
    GardenaRateLimitError,
    GardenaWebSocket,
)

from .base_coordinator import BaseSmartSystemCoordinator, CoordinatorConfig
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_LOCATION_ID,
    DEFAULT_LOCAL_PORT,
    DEFAULT_POLL_INTERVAL_GARDENA,
    DOMAIN,
    OPT_LOCAL_ENABLE,
    OPT_LOCAL_HOST,
    OPT_LOCAL_PASSWORD,
    OPT_LOCAL_PORT,
    RATE_LIMIT_COOLDOWN,
    SCAN_INTERVAL,
    SCAN_INTERVAL_WS_CONNECTED,
)
from .local_channel import GardenaLocalChannel
from .local_translate import (
    apply_local_state,
    build_local_command,
    index_local_devices_by_serial,
)

_LOGGER = logging.getLogger(__name__)

_GARDENA_CONFIG = CoordinatorConfig(
    coordinator_name=DOMAIN,
    api_label="Gardena",
    scan_interval=SCAN_INTERVAL,
    scan_interval_ws=SCAN_INTERVAL_WS_CONNECTED,
    rate_limit_cooldown=RATE_LIMIT_COOLDOWN,
    default_poll_minutes=DEFAULT_POLL_INTERVAL_GARDENA,
    ws_issue_key="websocket_connection_failed",
    app_blocked_issue_key="husqvarna_application_blocked",
    auth_error_type=GardenaAuthenticationError,
    connection_error_type=GardenaConnectionError,
    rate_limit_error_type=GardenaRateLimitError,
    device_serial_fn=lambda d: d.serial,
)


class GardenaCoordinator(BaseSmartSystemCoordinator[Device]):
    """Manages data fetching and WebSocket updates for one Gardena location."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        websession: aiohttp.ClientSession,
    ) -> None:
        """Initialize the coordinator."""
        auth = GardenaAuth(
            client_id=entry.data[CONF_CLIENT_ID],
            client_secret=entry.data[CONF_CLIENT_SECRET],
            websession=websession,
        )
        super().__init__(hass, entry, websession, auth, _GARDENA_CONFIG)
        self._client = GardenaClient(auth, websession)
        self._location_id: str = entry.data[CONF_LOCATION_ID]
        # Optional local gateway channel (see local_channel / local_translate).
        self._local_channel: GardenaLocalChannel | None = None
        self._local_connected = False
        # device_id -> "local" | "cloud": route the last command actually took.
        self._last_command_source: dict[str, str] = {}

    @property
    def location_id(self) -> str:
        """The Gardena location ID this coordinator manages."""
        return self._location_id

    @property
    def client(self) -> GardenaClient:
        """The REST API client (used by entity platforms to send commands)."""
        return self._client

    async def _async_fetch_devices(self) -> dict[str, Device]:
        """Fetch devices from the Gardena API."""
        devices = await self._client.async_get_devices(self._location_id)
        await self._async_ensure_local_channel()
        return devices

    # ── Local gateway channel (optional, takes precedence) ─────────
    @property
    def local_connected(self) -> bool:
        """Whether the local gateway link is currently up."""
        return self._local_connected

    def last_command_source(self, device_id: str) -> str | None:
        """Return 'local' or 'cloud' for the most recent command to a device."""
        return self._last_command_source.get(device_id)

    async def _async_ensure_local_channel(self) -> None:
        """Start, stop, or leave the local channel per the current options."""
        options = self.config_entry.options
        host = options.get(OPT_LOCAL_HOST)
        if not options.get(OPT_LOCAL_ENABLE) or not host:
            if self._local_channel is not None:
                await self._local_channel.async_stop()
                self._local_channel = None
                self._set_local_connected(False)
            return
        if self._local_channel is None:
            self._local_channel = GardenaLocalChannel(
                self.hass,
                host,
                options.get(OPT_LOCAL_PASSWORD, ""),
                int(options.get(OPT_LOCAL_PORT, DEFAULT_LOCAL_PORT)),
                on_devices_updated=self._on_local_devices_updated,
                on_connection_change=self._set_local_connected,
            )
            await self._local_channel.async_start()

    @callback
    def _on_local_devices_updated(self, local_devices: Any) -> None:
        """Overlay fresh local state onto the cloud model (local takes precedence)."""
        self._apply_local_overlay(local_devices)

    def _apply_local_overlay(self, local_devices: Any) -> None:
        if not self.data:
            return
        by_serial = index_local_devices_by_serial(local_devices)
        changed = False
        for device in self.data.values():
            local = by_serial.get(device.serial)
            if local is not None and apply_local_state(local, device):
                changed = True
        if changed:
            self.async_set_updated_data(self.data)

    @callback
    def _set_local_connected(self, value: bool) -> None:
        if value != self._local_connected:
            self._local_connected = value
            self.async_update_listeners()

    def _on_device_update(self, device_id: str, device: Device) -> None:
        """Apply the cloud push, then re-assert local state so local wins."""
        super()._on_device_update(device_id, device)
        channel = self._local_channel
        if channel is None or not channel.connected or not self.data:
            return
        cloud_device = self.data.get(device_id)
        if cloud_device is None:
            return
        local = index_local_devices_by_serial(channel.devices).get(cloud_device.serial)
        if local is not None and apply_local_state(local, cloud_device):
            self.async_set_updated_data(self.data)

    async def async_send_command(
        self, service_id: str, control_type: str, command: str, **params: int
    ) -> None:
        """Send a device command local-first, falling back to the cloud API.

        Mirrors ``client.async_send_command`` so entity platforms can call it in
        place of the cloud client. Records which route actually carried the
        command (see ``last_command_source``). A cloud-path failure propagates
        exactly as before so the existing retry/timeout logic is unaffected.
        """
        device_id = service_id.split(":")[0]
        if await self._try_local_command(device_id, service_id, control_type, command, params):
            self._last_command_source[device_id] = "local"
            return
        # Forward as keywords to preserve the exact cloud-client call convention.
        await self._client.async_send_command(
            service_id=service_id, control_type=control_type, command=command, **params
        )
        self._last_command_source[device_id] = "cloud"

    async def _try_local_command(
        self,
        device_id: str,
        service_id: str,
        control_type: str,
        command: str,
        params: dict[str, int],
    ) -> bool:
        """Attempt the command over the local channel; True only if acknowledged."""
        channel = self._local_channel
        if channel is None or not channel.connected or not self.data:
            return False
        cloud_device = self.data.get(device_id)
        if cloud_device is None:
            return False
        local = index_local_devices_by_serial(channel.devices).get(cloud_device.serial)
        if local is None:
            return False
        request = build_local_command(
            local, cloud_device, service_id, control_type, command, params.get("seconds")
        )
        if request is None:
            return False
        return await channel.async_send_command(request)

    async def async_shutdown(self) -> None:
        """Stop the local channel, then run the shared shutdown."""
        if self._local_channel is not None:
            await self._local_channel.async_stop()
            self._local_channel = None
        await super().async_shutdown()

    async def _async_get_ws_url(self, devices: dict[str, Device]) -> str:
        """Obtain the WebSocket URL from the Gardena API."""
        return await self._client.async_get_websocket_url(self._location_id)

    def _create_websocket(
        self,
        auth: Any,
        websession: aiohttp.ClientSession,
        devices: dict[str, Device],
        on_update: Any,
        on_error: Any,
    ) -> GardenaWebSocket:
        """Construct the Gardena WebSocket client."""
        return GardenaWebSocket(
            auth=auth,
            websession=websession,
            devices=devices,
            on_update=on_update,
            on_error=on_error,
        )

    # Dispatch table for inbound MQTT commands.
    # Value = (control_type, command, needs_duration_param).
    # Adding a new action is a single-line change here.
    _MQTT_DISPATCH: ClassVar[dict[str, tuple[str, str, bool]]] = {
        "start_watering": ("VALVE_CONTROL", "START_SECONDS_TO_OVERRIDE", True),
        "stop_watering": ("VALVE_CONTROL", "STOP_UNTIL_NEXT_TASK", False),
        "turn_on": ("POWER_SOCKET_CONTROL", "START_SECONDS_TO_OVERRIDE", True),
        "turn_off": ("POWER_SOCKET_CONTROL", "STOP_UNTIL_NEXT_TASK", False),
        "park": ("MOWER_CONTROL", "PARK_UNTIL_FURTHER_NOTICE", False),
        "resume": ("MOWER_CONTROL", "START_DONT_OVERRIDE", False),
    }

    async def _async_handle_mqtt_command(self, device_id: str, payload: dict[str, Any]) -> None:
        """Handle inbound MQTT commands for Gardena devices.

        Expected payload: {"action": "start_watering", "duration": 30, "service_id": "..."}
        """
        action = payload.get("action", "")
        spec = self._MQTT_DISPATCH.get(action)
        if spec is None:
            _LOGGER.warning(
                "Unknown MQTT action '%s' for device %s",
                action,
                device_id,
            )
            return

        service_id = payload.get("service_id", device_id)
        duration = payload.get("duration")
        control_type, command, needs_duration = spec

        try:
            self.check_command_throttle()
        except HomeAssistantError:
            _LOGGER.warning("MQTT command throttled for %s", device_id)
            return

        # Count before dispatch — any failed PUT still counts against quota.
        self._api_budget.increment()

        kwargs: dict[str, int] = {}
        if needs_duration:
            minutes = int(duration) if duration else 60
            kwargs["seconds"] = minutes * 60

        try:
            await self._client.async_send_command(service_id, control_type, command, **kwargs)
        except GardenaException:
            _LOGGER.exception(
                "MQTT command '%s' failed for %s",
                action,
                device_id,
            )
            return
        _LOGGER.info(
            "MQTT command '%s' executed for %s",
            action,
            device_id,
        )
