"""OAuth2 token management for the Gardena / Husqvarna authentication API."""

from __future__ import annotations

import time
from typing import Any

import aiohttp

from .const import (
    AUTH_REVOKE_URL,
    AUTH_TOKEN_URL,
    REQUEST_TIMEOUT,
    TOKEN_REFRESH_BUFFER_SECONDS,
)
from .exceptions import GardenaAuthenticationError, GardenaConnectionError, GardenaRateLimitError


class GardenaAuth:
    """Manages OAuth2 tokens for the Husqvarna authentication API.

    Callers are responsible for providing and reusing an ``aiohttp.ClientSession``.
    This class does not create sessions internally (platinum: inject-websession).
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        websession: aiohttp.ClientSession,
    ) -> None:
        """Initialize with application credentials and an injected session."""
        self._client_id = client_id
        self._client_secret = client_secret
        self._websession = websession

        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at: float = 0.0

    @property
    def client_id(self) -> str:
        """The application client ID (also used as X-Api-Key)."""
        return self._client_id

    @property
    def access_token(self) -> str | None:
        """Current access token, or None if not yet acquired."""
        return self._access_token

    @property
    def is_token_valid(self) -> bool:
        """True if the access token exists and is not about to expire."""
        return (
            self._access_token is not None
            and time.monotonic() < self._token_expires_at - TOKEN_REFRESH_BUFFER_SECONDS
        )

    async def async_ensure_valid_token(self) -> str:
        """Return a valid access token, refreshing or re-acquiring as needed.

        Raises:
            GardenaAuthenticationError: if authentication fails.
            GardenaConnectionError: if a network error occurs.
        """
        if self.is_token_valid:
            assert self._access_token is not None
            return self._access_token

        if self._refresh_token:
            try:
                return await self._async_refresh_token()
            except GardenaAuthenticationError:
                # Refresh token expired; fall through to re-authenticate
                self._refresh_token = None

        return await self._async_acquire_token()

    async def _async_acquire_token(self) -> str:
        """Acquire a new token using client credentials."""
        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        return await self._async_post_token(data)

    async def _async_refresh_token(self) -> str:
        """Refresh the access token using the stored refresh token."""
        assert self._refresh_token is not None
        data = {
            "grant_type": "refresh_token",
            "client_id": self._client_id,
            "refresh_token": self._refresh_token,
        }
        return await self._async_post_token(data)

    async def _async_post_token(self, data: dict[str, str]) -> str:
        """Post to the token endpoint and update stored tokens."""
        try:
            async with self._websession.post(
                AUTH_TOKEN_URL,
                data=data,
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status == 400:
                    body = await resp.json()
                    raise GardenaAuthenticationError(
                        f"Invalid credentials: {body.get('error_description', '')}"
                    )
                if resp.status == 401:
                    raise GardenaAuthenticationError(
                        "Token refresh rejected — re-authentication required"
                    )
                if resp.status == 429:
                    raise GardenaRateLimitError("Rate limited by Husqvarna auth endpoint")
                resp.raise_for_status()
                token_data: dict[str, Any] = await resp.json()
        except aiohttp.ClientError as err:
            raise GardenaConnectionError(f"Token request failed: {err}") from err

        self._access_token = str(token_data["access_token"])
        refresh = token_data.get("refresh_token")
        self._refresh_token = str(refresh) if refresh is not None else None
        expires_in = int(token_data.get("expires_in", 3600))
        self._token_expires_at = time.monotonic() + expires_in
        return self._access_token

    async def async_revoke_token(self) -> None:
        """Revoke the current access token (call on logout/removal)."""
        if self._access_token is None:
            return
        try:
            async with self._websession.post(
                AUTH_REVOKE_URL,
                data={"token": self._access_token, "client_id": self._client_id},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                await resp.read()
        except aiohttp.ClientError:
            pass  # Best-effort revocation; don't raise
        finally:
            self._access_token = None
            self._refresh_token = None
            self._token_expires_at = 0.0
