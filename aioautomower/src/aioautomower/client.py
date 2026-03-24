"""REST API client for the Husqvarna Automower Connect API v1."""

from __future__ import annotations

from typing import Any, cast

import aiohttp
from aiogardenasmart.auth import GardenaAuth

from .const import API_BASE_URL, AUTHORIZATION_PROVIDER, REQUEST_TIMEOUT, ActionType
from .exceptions import (
    AutomowerAuthenticationError,
    AutomowerConnectionError,
    AutomowerForbiddenError,
    AutomowerRateLimitError,
    AutomowerRequestError,
)
from .models import AutomowerDevice


class AutomowerClient:
    """Async REST client for the Husqvarna Automower Connect API v1.

    Reuses ``GardenaAuth`` for OAuth2 token management since both APIs use
    the same Husqvarna authentication endpoint.

    An ``aiohttp.ClientSession`` must be provided by the caller.
    """

    def __init__(self, auth: GardenaAuth, websession: aiohttp.ClientSession) -> None:
        """Initialize with an auth manager and an injected session."""
        self._auth = auth
        self._websession = websession

    async def _async_headers(self) -> dict[str, str]:
        """Build authenticated request headers."""
        token = await self._auth.async_ensure_valid_token()
        return {
            "Authorization": f"Bearer {token}",
            "Authorization-Provider": AUTHORIZATION_PROVIDER,
            "X-Api-Key": self._auth.client_id,
            "Accept": "application/vnd.api+json",
        }

    async def _async_request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an authenticated request and return parsed JSON.

        Raises:
            AutomowerAuthenticationError: on 401.
            AutomowerForbiddenError: on 403.
            AutomowerRateLimitError: on 429.
            AutomowerRequestError: on other 4xx/5xx.
            AutomowerConnectionError: on network errors.
        """
        headers = await self._async_headers()
        if json is not None:
            headers["Content-Type"] = "application/vnd.api+json"
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
                    raise AutomowerAuthenticationError("Access token rejected by API")
                if resp.status == 403:
                    raise AutomowerForbiddenError(
                        "API key not authorized for Automower Connect API — "
                        "check the connected APIs on the Husqvarna Developer Portal"
                    )
                if resp.status == 429:
                    raise AutomowerRateLimitError(
                        "Automower API rate limit reached. Wait a few minutes and try again."
                    )
                if resp.status >= 400:
                    body = await resp.text()
                    raise AutomowerRequestError(resp.status, body)
                if resp.status in (202, 204):
                    return {}
                return cast(dict[str, Any], await resp.json(content_type=None))
        except (aiohttp.ClientError, TimeoutError) as err:
            raise AutomowerConnectionError(f"Request to {url} failed: {err}") from err

    # ── Mower queries ──────────────────────────────────────────────

    async def async_get_mowers(self) -> dict[str, AutomowerDevice]:
        """Return all mowers, keyed by mower ID."""
        data = await self._async_request("GET", "/mowers")
        mowers: dict[str, AutomowerDevice] = {}
        for item in data.get("data", []):
            device = AutomowerDevice.from_api(item)
            mowers[device.mower_id] = device
        return mowers

    async def async_get_mower(self, mower_id: str) -> AutomowerDevice:
        """Return a single mower's full data."""
        data = await self._async_request("GET", f"/mowers/{mower_id}")
        return AutomowerDevice.from_api(data.get("data", data))

    # ── Commands / Actions ─────────────────────────────────────────

    async def async_send_action(
        self, mower_id: str, action: str, duration: int | None = None
    ) -> None:
        """Send a control action to a mower.

        Args:
            mower_id: The mower UUID.
            action: One of ActionType values (Start, Pause, etc.).
            duration: Duration in minutes (only for Start action).
        """
        payload: dict[str, Any] = {
            "data": {
                "type": action,
            }
        }
        if duration is not None and action == ActionType.START:
            payload["data"]["attributes"] = {"duration": duration}
        await self._async_request("POST", f"/mowers/{mower_id}/actions", json=payload)

    async def async_start(self, mower_id: str, duration: int | None = None) -> None:
        """Start mowing, optionally for a specific duration in minutes."""
        await self.async_send_action(mower_id, ActionType.START, duration=duration)

    async def async_pause(self, mower_id: str) -> None:
        """Pause the mower."""
        await self.async_send_action(mower_id, ActionType.PAUSE)

    async def async_park_until_next_schedule(self, mower_id: str) -> None:
        """Park until the next scheduled task."""
        await self.async_send_action(mower_id, ActionType.PARK_UNTIL_NEXT_SCHEDULE)

    async def async_park_until_further_notice(self, mower_id: str) -> None:
        """Park until further notice (override schedule)."""
        await self.async_send_action(mower_id, ActionType.PARK_UNTIL_FURTHER_NOTICE)

    async def async_resume_schedule(self, mower_id: str) -> None:
        """Resume the mower's schedule."""
        await self.async_send_action(mower_id, ActionType.RESUME_SCHEDULE)

    # ── Settings ───────────────────────────────────────────────────

    async def async_set_cutting_height(self, mower_id: str, height: int) -> None:
        """Set the global cutting height (1-9)."""
        payload: dict[str, Any] = {
            "data": {
                "type": "settings",
                "attributes": {"cuttingHeight": height},
            }
        }
        await self._async_request("PATCH", f"/mowers/{mower_id}/settings", json=payload)

    async def async_set_headlight_mode(self, mower_id: str, mode: str) -> None:
        """Set the headlight mode."""
        payload: dict[str, Any] = {
            "data": {
                "type": "settings",
                "attributes": {"headlight": {"mode": mode}},
            }
        }
        await self._async_request("PATCH", f"/mowers/{mower_id}/settings", json=payload)

    # ── Calendar ───────────────────────────────────────────────────

    async def async_update_calendar(self, mower_id: str, tasks: list[dict[str, Any]]) -> None:
        """Update the mowing schedule calendar."""
        payload: dict[str, Any] = {
            "data": {
                "type": "calendar",
                "attributes": {"tasks": tasks},
            }
        }
        await self._async_request("PATCH", f"/mowers/{mower_id}/calendar", json=payload)

    # ── Work Areas ─────────────────────────────────────────────────

    async def async_set_work_area_cutting_height(
        self, mower_id: str, work_area_id: int, cutting_height: int
    ) -> None:
        """Set cutting height for a specific work area (0-100)."""
        payload: dict[str, Any] = {
            "data": {
                "type": "workArea",
                "id": str(work_area_id),
                "attributes": {"cuttingHeight": cutting_height},
            }
        }
        await self._async_request(
            "PATCH", f"/mowers/{mower_id}/workAreas/{work_area_id}", json=payload
        )

    # ── Stay-Out Zones ─────────────────────────────────────────────

    async def async_set_stay_out_zone(self, mower_id: str, zone_id: str, enabled: bool) -> None:
        """Enable or disable a stay-out zone."""
        payload: dict[str, Any] = {
            "data": {
                "type": "stayOutZone",
                "id": zone_id,
                "attributes": {"enable": enabled},
            }
        }
        await self._async_request(
            "PATCH", f"/mowers/{mower_id}/stayOutZones/{zone_id}", json=payload
        )
