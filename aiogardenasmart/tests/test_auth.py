"""Tests for GardenaAuth OAuth2 token management."""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator

import aiohttp
import pytest
from aioresponses import aioresponses

from aiogardenasmart.auth import GardenaAuth
from aiogardenasmart.const import AUTH_REVOKE_URL, AUTH_TOKEN_URL
from aiogardenasmart.exceptions import GardenaAuthenticationError, GardenaConnectionError

from .fixtures import TOKEN_RESPONSE, TOKEN_RESPONSE_NO_REFRESH


@pytest.fixture
async def session() -> AsyncGenerator[aiohttp.ClientSession, None]:
    async with aiohttp.ClientSession() as s:
        yield s


@pytest.fixture
async def auth(session: aiohttp.ClientSession) -> GardenaAuth:
    return GardenaAuth("test-client-id", "test-secret", session)


class TestTokenAcquisition:
    async def test_acquire_token_success(
        self, auth: GardenaAuth
    ) -> None:
        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, payload=TOKEN_RESPONSE)
            token = await auth.async_ensure_valid_token()

        assert token == "test-access-token"
        assert auth.access_token == "test-access-token"

    async def test_acquire_token_stores_refresh_token(
        self, auth: GardenaAuth
    ) -> None:
        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, payload=TOKEN_RESPONSE)
            await auth.async_ensure_valid_token()

        assert auth._refresh_token == "test-refresh-token"

    async def test_acquire_token_without_refresh_token(
        self, auth: GardenaAuth
    ) -> None:
        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, payload=TOKEN_RESPONSE_NO_REFRESH)
            token = await auth.async_ensure_valid_token()

        assert token == "test-access-token"
        assert auth._refresh_token is None

    async def test_invalid_credentials_raises_auth_error(
        self, auth: GardenaAuth
    ) -> None:
        with aioresponses() as m:
            m.post(
                AUTH_TOKEN_URL,
                status=400,
                payload={"error": "invalid_client", "error_description": "Bad credentials"},
            )
            with pytest.raises(GardenaAuthenticationError, match="Invalid credentials"):
                await auth.async_ensure_valid_token()

    async def test_401_raises_auth_error(self, auth: GardenaAuth) -> None:
        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, status=401, payload={})
            with pytest.raises(GardenaAuthenticationError):
                await auth.async_ensure_valid_token()

    async def test_network_error_raises_connection_error(
        self, auth: GardenaAuth
    ) -> None:
        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, exception=aiohttp.ClientConnectionError())
            with pytest.raises(GardenaConnectionError):
                await auth.async_ensure_valid_token()


class TestTokenValidity:
    async def test_valid_token_not_refreshed(self, auth: GardenaAuth) -> None:
        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, payload=TOKEN_RESPONSE)
            await auth.async_ensure_valid_token()

        # Second call should use cached token — no new HTTP request
        token = await auth.async_ensure_valid_token()
        assert token == "test-access-token"

    async def test_expired_token_triggers_refresh(self, auth: GardenaAuth) -> None:
        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, payload=TOKEN_RESPONSE)
            await auth.async_ensure_valid_token()

        auth._token_expires_at = time.monotonic() - 1  # manually expire

        refreshed_payload = {**TOKEN_RESPONSE, "access_token": "refreshed-token"}
        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, payload=refreshed_payload)
            token = await auth.async_ensure_valid_token()

        assert token == "refreshed-token"

    async def test_failed_refresh_falls_back_to_reauth(self, auth: GardenaAuth) -> None:
        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, payload=TOKEN_RESPONSE)
            await auth.async_ensure_valid_token()

        auth._token_expires_at = time.monotonic() - 1

        reauth_payload = {**TOKEN_RESPONSE, "access_token": "reauth-token"}
        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, status=401, payload={})   # refresh fails
            m.post(AUTH_TOKEN_URL, payload=reauth_payload)   # re-auth succeeds
            token = await auth.async_ensure_valid_token()

        assert token == "reauth-token"

    async def test_is_token_valid_false_when_no_token(self, auth: GardenaAuth) -> None:
        assert auth.is_token_valid is False

    async def test_is_token_valid_true_after_acquire(self, auth: GardenaAuth) -> None:
        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, payload=TOKEN_RESPONSE)
            await auth.async_ensure_valid_token()

        assert auth.is_token_valid is True


class TestTokenRevocation:
    async def test_revoke_clears_tokens(self, auth: GardenaAuth) -> None:
        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, payload=TOKEN_RESPONSE)
            await auth.async_ensure_valid_token()

        with aioresponses() as m:
            m.post(AUTH_REVOKE_URL, status=200, payload={})
            await auth.async_revoke_token()

        assert auth.access_token is None
        assert auth._refresh_token is None

    async def test_revoke_noop_when_no_token(self, auth: GardenaAuth) -> None:
        await auth.async_revoke_token()  # should not raise

    async def test_revoke_ignores_network_error(self, auth: GardenaAuth) -> None:
        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, payload=TOKEN_RESPONSE)
            await auth.async_ensure_valid_token()

        with aioresponses() as m:
            m.post(AUTH_REVOKE_URL, exception=aiohttp.ClientConnectionError())
            await auth.async_revoke_token()  # should not raise

        assert auth.access_token is None
