"""REST API client for the Gardena Smart System API v2."""

from __future__ import annotations

import uuid
from typing import Any, cast

import aiohttp

from .auth import GardenaAuth
from .const import (
    API_BASE_URL,
    AUTHORIZATION_PROVIDER,
    CONTENT_TYPE_JSON_API,
    REQUEST_TIMEOUT,
    ServiceType,
)
from .exceptions import (
    GardenaAuthenticationError,
    GardenaConnectionError,
    GardenaForbiddenError,
    GardenaRateLimitError,
    GardenaRequestError,
)
from .models import (
    CommonService,
    Device,
    Location,
    MowerService,
    PowerSocketService,
    SensorService,
    ValveService,
    ValveSetService,
)


class GardenaClient:
    """Async REST client for the Gardena Smart System API v2.

    An ``aiohttp.ClientSession`` must be provided by the caller — this client
    does not create sessions internally (platinum: inject-websession rule).
    """

    def __init__(self, auth: GardenaAuth, websession: aiohttp.ClientSession) -> None:
        """Initialize with an auth manager and an injected session."""
        self._auth = auth
        self._websession = websession

    async def _async_headers(self, include_content_type: bool = False) -> dict[str, str]:
        """Build authenticated request headers.

        Args:
            include_content_type: When True, adds the JSON:API Content-Type header
                required for POST/PUT requests with a body.
        """
        token = await self._auth.async_ensure_valid_token()
        headers: dict[str, str] = {
            "Authorization": f"Bearer {token}",
            "Authorization-Provider": AUTHORIZATION_PROVIDER,
            "X-Api-Key": self._auth.client_id,
            "Accept": CONTENT_TYPE_JSON_API,
        }
        if include_content_type:
            headers["Content-Type"] = CONTENT_TYPE_JSON_API
        return headers

    async def _async_request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        include_content_type: bool = False,
    ) -> dict[str, Any]:
        """Execute an authenticated request and return parsed JSON.

        Args:
            method: HTTP method (GET, POST, PUT).
            path: API path relative to the base URL.
            json: Optional JSON body (sets Content-Type automatically via aiohttp).
            include_content_type: Pass True for POST/PUT to add the JSON:API
                Content-Type header explicitly.

        Raises:
            GardenaAuthenticationError: on 401.
            GardenaForbiddenError: on 403.
            GardenaRequestError: on other 4xx/5xx.
            GardenaConnectionError: on network errors.
        """
        headers = await self._async_headers(include_content_type=include_content_type)
        url = f"{API_BASE_URL}{path}"
        try:
            async with self._websession.request(
                method,
                url,
                headers=headers,
                json=json,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status == 401:
                    raise GardenaAuthenticationError("Access token rejected by API")
                if resp.status == 403:
                    raise GardenaForbiddenError(
                        "API key not authorized — check application connection on developer portal"
                    )
                if resp.status == 429:
                    body = await resp.text()
                    raise GardenaRateLimitError(
                        "API rate limit reached or API key temporarily blocked. "
                        "Wait a few minutes and try again, or create a new application "
                        "in the Husqvarna Developer Portal."
                    )
                if resp.status >= 400:
                    body = await resp.text()
                    raise GardenaRequestError(resp.status, body)
                if resp.status == 204:
                    return {}
                return cast(dict[str, Any], await resp.json(content_type=None))
        except (aiohttp.ClientError, TimeoutError) as err:
            raise GardenaConnectionError(f"Request to {url} failed: {err}") from err

    async def async_get_locations(self) -> list[Location]:
        """Return all locations (gardens) for the authenticated account."""
        data = await self._async_request("GET", "/locations")
        return [Location.from_api(item) for item in data.get("data", [])]

    async def async_get_devices(self, location_id: str) -> dict[str, Device]:
        """Return all devices for a location, keyed by device ID.

        Parses the JSON:API ``included`` sideloaded array to reconstruct each
        device with its complete set of services.
        """
        data = await self._async_request("GET", f"/locations/{location_id}")
        return _parse_devices(data, location_id)

    async def async_get_websocket_url(self, location_id: str) -> str:
        """Request a WebSocket URL for real-time updates for a location."""
        payload: dict[str, Any] = {
            "data": {
                "id": str(uuid.uuid4()),
                "type": "WEBSOCKET",
                "attributes": {"locationId": location_id},
            }
        }
        data = await self._async_request(
            "POST",
            "/websocket",
            json=payload,
            include_content_type=True,
        )
        return str(data["data"]["attributes"]["url"])

    async def async_send_command(
        self,
        service_id: str,
        control_type: str,
        command: str,
        **params: int | str,
    ) -> None:
        """Send a command to a service.

        Args:
            service_id: The service UUID (e.g., valve service ID).
            control_type: The control type string (e.g., ``VALVE_CONTROL``).
            command: The command name (e.g., ``START_SECONDS_TO_OVERRIDE``).
            **params: Additional int or str command parameters (e.g., ``seconds=3600``).

        Raises:
            GardenaRequestError: if the command is rejected.
        """
        attributes: dict[str, Any] = {"command": command, **params}
        payload: dict[str, Any] = {
            "data": {
                "id": str(uuid.uuid4()),
                "type": control_type,
                "attributes": attributes,
            }
        }
        await self._async_request(
            "PUT",
            f"/command/{service_id}",
            json=payload,
            include_content_type=True,
        )


def _parse_devices(
    response: dict[str, Any], location_id: str
) -> dict[str, Device]:
    """Parse a location response into Device objects keyed by device ID."""
    devices: dict[str, Device] = {}

    for item in response.get("included", []):
        item_type: str = str(item.get("type", ""))
        item_id: str = str(item["id"])

        # Derive the base device ID (valve IDs look like "uuid:1")
        base_device_id = item_id.split(":")[0]

        if item_type == "DEVICE":
            if base_device_id not in devices:
                devices[base_device_id] = Device(
                    device_id=base_device_id,
                    location_id=location_id,
                )
            continue

        # Ensure the parent Device exists
        if base_device_id not in devices:
            devices[base_device_id] = Device(
                device_id=base_device_id,
                location_id=location_id,
            )
        device = devices[base_device_id]

        if item_type == ServiceType.COMMON:
            device.common = CommonService.from_api(item)
        elif item_type == ServiceType.MOWER:
            device.mower = MowerService.from_api(item)
        elif item_type == ServiceType.VALVE:
            valve = ValveService.from_api(item)
            device.valves[item_id] = valve
        elif item_type == ServiceType.VALVE_SET:
            device.valve_set = ValveSetService.from_api(item)
        elif item_type == ServiceType.SENSOR:
            device.sensor = SensorService.from_api(item)
        elif item_type == ServiceType.POWER_SOCKET:
            device.power_socket = PowerSocketService.from_api(item)

    return devices
