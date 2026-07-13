"""Coverage for the credential-test token-revocation error paths."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.gardena_smart_system_ng.config_flow import (
    GardenaSmartSystemConfigFlow,
)

_CF = "custom_components.gardena_smart_system_ng.config_flow"


async def test_gardena_credential_test_swallows_revoke_error(
    hass: HomeAssistant,
) -> None:
    auth = MagicMock()
    auth.async_revoke_token = AsyncMock(side_effect=aiohttp.ClientError("no net"))
    location = MagicMock(location_id="loc-1")
    location.name = "Garden"  # `name=` is a reserved MagicMock kwarg, set it explicitly
    client = MagicMock()
    client.async_get_locations = AsyncMock(return_value=[location])
    with (
        patch(f"{_CF}.GardenaAuth", return_value=auth),
        patch(f"{_CF}.GardenaClient", return_value=client),
    ):
        locations, error = await GardenaSmartSystemConfigFlow._async_test_gardena(
            async_get_clientsession(hass), "id", "secret"
        )
    assert error == ""  # revoke failure is logged, not raised
    assert locations == [{"id": "loc-1", "name": "Garden"}]


async def test_automower_credential_test_swallows_revoke_error(
    hass: HomeAssistant,
) -> None:
    auth = MagicMock()
    auth.async_revoke_token = AsyncMock(side_effect=aiohttp.ClientError("no net"))
    client = MagicMock()
    client.async_get_mowers = AsyncMock(return_value=[])
    with (
        patch(f"{_CF}.GardenaAuth", return_value=auth),
        patch("aioautomower.AutomowerClient", return_value=client),
    ):
        error = await GardenaSmartSystemConfigFlow._async_test_automower(
            hass, async_get_clientsession(hass), "id", "secret"
        )
    assert error == ""  # revoke failure is logged, not raised


async def test_automower_credential_test_routes_import_through_executor(
    hass: HomeAssistant,
) -> None:
    """Regression test for #47 ("Detected blocking call").

    `aioautomower` (and its `.exceptions` submodule) may be imported for the
    first time in this process inside `_async_test_automower` — the same
    anti-pattern as the deferred coordinator imports in `__init__.py`. This
    asserts the fix (routing through
    `homeassistant.helpers.importlib.async_import_module`) is actually used.
    """
    from homeassistant.helpers.importlib import (
        async_import_module as real_async_import_module,
    )

    auth = MagicMock()
    auth.async_revoke_token = AsyncMock()
    client = MagicMock()
    client.async_get_mowers = AsyncMock(return_value=[])
    with (
        patch(f"{_CF}.GardenaAuth", return_value=auth),
        patch("aioautomower.AutomowerClient", return_value=client),
        patch(
            f"{_CF}.async_import_module",
            AsyncMock(wraps=real_async_import_module),
        ) as mock_import,
    ):
        error = await GardenaSmartSystemConfigFlow._async_test_automower(
            hass, async_get_clientsession(hass), "id", "secret"
        )

    assert error == ""
    mock_import.assert_any_await(hass, "aioautomower")
    mock_import.assert_any_await(hass, "aioautomower.exceptions")
