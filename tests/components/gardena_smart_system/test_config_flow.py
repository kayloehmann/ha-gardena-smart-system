"""Tests for the Gardena Smart System config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.gardena_smart_system.const import (
    API_TYPE_AUTOMOWER,
    API_TYPE_GARDENA,
    CONF_API_TYPE,
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

_PATCH_AUTH = "custom_components.gardena_smart_system.config_flow.GardenaAuth"
_PATCH_CLIENT = "custom_components.gardena_smart_system.config_flow.GardenaClient"
_PATCH_AM_CLIENT = "custom_components.gardena_smart_system.config_flow.AutomowerClient"


async def _init_user_step(hass: HomeAssistant) -> dict:
    """Start the config flow and return the user step result."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _submit_credentials(
    hass: HomeAssistant,
    flow_id: str,
    *,
    auth_side_effect: Exception | None = None,
) -> dict:
    """Submit credentials in user step, patching auth validation."""
    mock_auth = AsyncMock()
    mock_auth.async_ensure_valid_token = AsyncMock(side_effect=auth_side_effect)
    mock_auth.async_revoke_token = AsyncMock()

    with patch(_PATCH_AUTH, return_value=mock_auth):
        return await hass.config_entries.flow.async_configure(
            flow_id,
            {CONF_CLIENT_ID: MOCK_CLIENT_ID, CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET},
        )


async def _submit_api_type_gardena(
    hass: HomeAssistant,
    flow_id: str,
    locations: list,
) -> dict:
    """Submit api_type=gardena, patching the Gardena client."""
    mock_client = AsyncMock()
    mock_client.async_get_locations = AsyncMock(return_value=locations)

    with patch(_PATCH_CLIENT, return_value=mock_client):
        return await hass.config_entries.flow.async_configure(
            flow_id,
            {CONF_API_TYPE: API_TYPE_GARDENA},
        )


class TestUserStep:
    async def test_shows_form_on_initial_load(self, hass: HomeAssistant) -> None:
        result = await _init_user_step(hass)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"

    async def test_valid_credentials_show_api_type_step(
        self, hass: HomeAssistant
    ) -> None:
        result = await _init_user_step(hass)
        result = await _submit_credentials(hass, result["flow_id"])

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "api_type"

    async def test_single_location_creates_entry(self, hass: HomeAssistant) -> None:
        result = await _init_user_step(hass)
        result = await _submit_credentials(hass, result["flow_id"])

        assert result["step_id"] == "api_type"
        result = await _submit_api_type_gardena(
            hass, result["flow_id"], [make_mock_location()]
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == MOCK_LOCATION_NAME
        assert result["data"][CONF_CLIENT_ID] == MOCK_CLIENT_ID
        assert result["data"][CONF_CLIENT_SECRET] == MOCK_CLIENT_SECRET
        assert result["data"][CONF_LOCATION_ID] == MOCK_LOCATION_ID
        assert result["data"][CONF_API_TYPE] == API_TYPE_GARDENA

    async def test_multiple_locations_shows_location_step(
        self, hass: HomeAssistant
    ) -> None:
        result = await _init_user_step(hass)
        result = await _submit_credentials(hass, result["flow_id"])

        result = await _submit_api_type_gardena(
            hass,
            result["flow_id"],
            [make_mock_location("loc1", "Garden 1"), make_mock_location("loc2", "Garden 2")],
        )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "location"

    async def test_invalid_auth_shows_error(self, hass: HomeAssistant) -> None:
        from aiogardenasmart.exceptions import GardenaAuthenticationError

        result = await _init_user_step(hass)
        result = await _submit_credentials(
            hass,
            result["flow_id"],
            auth_side_effect=GardenaAuthenticationError("bad creds"),
        )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"]["base"] == "invalid_auth"

    async def test_cannot_connect_shows_error(self, hass: HomeAssistant) -> None:
        from aiogardenasmart.exceptions import GardenaConnectionError

        result = await _init_user_step(hass)
        result = await _submit_credentials(
            hass,
            result["flow_id"],
            auth_side_effect=GardenaConnectionError("timeout"),
        )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"]["base"] == "cannot_connect"

    async def test_unknown_error_shows_error(self, hass: HomeAssistant) -> None:
        result = await _init_user_step(hass)
        result = await _submit_credentials(
            hass,
            result["flow_id"],
            auth_side_effect=RuntimeError("unexpected"),
        )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "unknown"


class TestApiTypeStep:
    async def test_automower_creates_entry(self, hass: HomeAssistant) -> None:
        result = await _init_user_step(hass)
        result = await _submit_credentials(hass, result["flow_id"])

        mock_am_client = AsyncMock()
        mock_am_client.async_get_mowers = AsyncMock(return_value={})

        with patch(_PATCH_AM_CLIENT, return_value=mock_am_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_API_TYPE: API_TYPE_AUTOMOWER},
            )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == "Automower Connect"
        assert result["data"][CONF_API_TYPE] == API_TYPE_AUTOMOWER

    async def test_automower_forbidden_shows_error(self, hass: HomeAssistant) -> None:
        from aioautomower.exceptions import AutomowerForbiddenError

        result = await _init_user_step(hass)
        result = await _submit_credentials(hass, result["flow_id"])

        mock_am_client = AsyncMock()
        mock_am_client.async_get_mowers = AsyncMock(
            side_effect=AutomowerForbiddenError("no access")
        )

        with patch(_PATCH_AM_CLIENT, return_value=mock_am_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_API_TYPE: API_TYPE_AUTOMOWER},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "api_type"
        assert result["errors"]["base"] == "automower_not_connected"


class TestLocationStep:
    async def test_location_step_creates_entry(self, hass: HomeAssistant) -> None:
        result = await _init_user_step(hass)
        result = await _submit_credentials(hass, result["flow_id"])

        result = await _submit_api_type_gardena(
            hass,
            result["flow_id"],
            [make_mock_location("loc1", "Garden 1"), make_mock_location("loc2", "Garden 2")],
        )

        assert result["step_id"] == "location"
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

        mock_client = AsyncMock()
        mock_client.async_get_locations = AsyncMock(
            return_value=[make_mock_location()]
        )
        with patch(_PATCH_CLIENT, return_value=mock_client):
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

        mock_client = AsyncMock()
        mock_client.async_get_locations = AsyncMock(
            side_effect=GardenaAuthenticationError("still bad")
        )
        with patch(_PATCH_CLIENT, return_value=mock_client):
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

        mock_client = AsyncMock()
        mock_client.async_get_locations = AsyncMock(
            return_value=[make_mock_location()]
        )
        with patch(_PATCH_CLIENT, return_value=mock_client):
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

        mock_client = AsyncMock()
        mock_client.async_get_locations = AsyncMock(
            side_effect=GardenaConnectionError("offline")
        )
        with patch(_PATCH_CLIENT, return_value=mock_client):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_CLIENT_ID: MOCK_CLIENT_ID, CONF_CLIENT_SECRET: MOCK_CLIENT_SECRET},
            )

        assert result["type"] == FlowResultType.FORM
        assert result["errors"]["base"] == "cannot_connect"
