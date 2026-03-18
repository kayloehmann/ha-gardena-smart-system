"""Tests for the Gardena Smart System config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.gardena_smart_system.const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_LOCATION_ID,
    DOMAIN,
)

from .conftest import (
    MOCK_CLIENT_ID,
    MOCK_CLIENT_SECRET,
    MOCK_LOCATION_ID,
    MOCK_LOCATION_NAME,
    make_mock_location,
)

_PATCH_CLIENT = (
    "custom_components.gardena_smart_system.config_flow.GardenaClient"
)


def _patch_client_with_locations(*locations: object) -> object:
    """Context manager: patch GardenaClient.async_get_locations."""
    mock_client = AsyncMock()
    mock_client.async_get_locations = AsyncMock(return_value=list(locations))

    patcher = patch(_PATCH_CLIENT)

    class _Ctx:
        def __enter__(self) -> AsyncMock:
            cls = patcher.__enter__()
            cls.return_value = mock_client
            return mock_client

        def __exit__(self, *args: object) -> None:
            patcher.__exit__(*args)

    return _Ctx()


class TestUserStep:
    async def test_shows_form_on_initial_load(self, hass: HomeAssistant) -> None:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"

    async def test_single_location_creates_entry(self, hass: HomeAssistant) -> None:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        with _patch_client_with_locations(make_mock_location()):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_CLIENT_ID: MOCK_CLIENT_ID, CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET},
            )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == MOCK_LOCATION_NAME
        assert result["data"][CONF_CLIENT_ID] == MOCK_CLIENT_ID
        assert result["data"][CONF_CLIENT_SECRET] == MOCK_CLIENT_SECRET
        assert result["data"][CONF_LOCATION_ID] == MOCK_LOCATION_ID

    async def test_multiple_locations_shows_location_step(
        self, hass: HomeAssistant
    ) -> None:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        with _patch_client_with_locations(
            make_mock_location("loc1", "Garden 1"),
            make_mock_location("loc2", "Garden 2"),
        ):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_CLIENT_ID: MOCK_CLIENT_ID, CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "location"

    async def test_invalid_auth_shows_error(self, hass: HomeAssistant) -> None:
        from aiogardenasmart.exceptions import GardenaAuthenticationError

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        with patch(_PATCH_CLIENT) as mock_cls:
            mock_client = AsyncMock()
            mock_client.async_get_locations = AsyncMock(
                side_effect=GardenaAuthenticationError("bad creds")
            )
            mock_cls.return_value = mock_client
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_CLIENT_ID: MOCK_CLIENT_ID, CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "invalid_auth"

    async def test_cannot_connect_shows_error(self, hass: HomeAssistant) -> None:
        from aiogardenasmart.exceptions import GardenaConnectionError

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        with patch(_PATCH_CLIENT) as mock_cls:
            mock_client = AsyncMock()
            mock_client.async_get_locations = AsyncMock(
                side_effect=GardenaConnectionError("timeout")
            )
            mock_cls.return_value = mock_client
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_CLIENT_ID: MOCK_CLIENT_ID, CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "cannot_connect"

    async def test_unknown_error_shows_error(self, hass: HomeAssistant) -> None:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        with patch(_PATCH_CLIENT) as mock_cls:
            mock_client = AsyncMock()
            mock_client.async_get_locations = AsyncMock(
                side_effect=RuntimeError("unexpected")
            )
            mock_cls.return_value = mock_client
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_CLIENT_ID: MOCK_CLIENT_ID, CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "unknown"


class TestLocationStep:
    async def test_location_step_creates_entry(self, hass: HomeAssistant) -> None:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        with _patch_client_with_locations(
            make_mock_location("loc1", "Garden 1"),
            make_mock_location("loc2", "Garden 2"),
        ):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_CLIENT_ID: MOCK_CLIENT_ID, CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET},
            )
            # Now at location step — pick the second garden
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_LOCATION_ID: "loc2"},
            )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_LOCATION_ID] == "loc2"
        assert result["title"] == "Garden 2"


class TestReauthFlow:
    async def test_reauth_shows_form(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        mock_config_entry.add_to_hass(hass)
        result = await mock_config_entry.start_reauth_flow(hass)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

    async def test_reauth_success_updates_credentials(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        mock_config_entry.add_to_hass(hass)
        result = await mock_config_entry.start_reauth_flow(hass)

        with _patch_client_with_locations(make_mock_location()):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_CLIENT_ID: "new-id", CONF_CLIENT_SECRET: "new-secret"},
            )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        assert mock_config_entry.data[CONF_CLIENT_ID] == "new-id"
        assert mock_config_entry.data[CONF_CLIENT_SECRET] == "new-secret"

    async def test_reauth_invalid_auth_shows_error(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        from aiogardenasmart.exceptions import GardenaAuthenticationError

        mock_config_entry.add_to_hass(hass)
        result = await mock_config_entry.start_reauth_flow(hass)

        with patch(_PATCH_CLIENT) as mock_cls:
            mock_client = AsyncMock()
            mock_client.async_get_locations = AsyncMock(
                side_effect=GardenaAuthenticationError("still bad")
            )
            mock_cls.return_value = mock_client
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_CLIENT_ID: "bad-id", CONF_CLIENT_SECRET: "bad-secret"},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "invalid_auth"


class TestReconfigureFlow:
    async def test_reconfigure_shows_form(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        mock_config_entry.add_to_hass(hass)
        result = await mock_config_entry.start_reconfigure_flow(hass)

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

    async def test_reconfigure_success_updates_credentials(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        mock_config_entry.add_to_hass(hass)
        result = await mock_config_entry.start_reconfigure_flow(hass)

        with _patch_client_with_locations(make_mock_location()):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_CLIENT_ID: "new-id", CONF_CLIENT_SECRET: "new-secret"},
            )

        assert result["type"] == FlowResultType.ABORT
        assert mock_config_entry.data[CONF_CLIENT_ID] == "new-id"

    async def test_reconfigure_cannot_connect_shows_error(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        from aiogardenasmart.exceptions import GardenaConnectionError

        mock_config_entry.add_to_hass(hass)
        result = await mock_config_entry.start_reconfigure_flow(hass)

        with patch(_PATCH_CLIENT) as mock_cls:
            mock_client = AsyncMock()
            mock_client.async_get_locations = AsyncMock(
                side_effect=GardenaConnectionError("offline")
            )
            mock_cls.return_value = mock_client
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_CLIENT_ID: MOCK_CLIENT_ID, CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "cannot_connect"
