"""Config flow for the Gardena Smart System integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from aioautomower import AutomowerClient
from aioautomower.exceptions import (
    AutomowerAuthenticationError,
    AutomowerConnectionError,
    AutomowerForbiddenError,
    AutomowerRateLimitError,
)
from aiogardenasmart import GardenaAuth, GardenaClient
from aiogardenasmart.exceptions import (
    GardenaAuthenticationError,
    GardenaConnectionError,
    GardenaForbiddenError,
    GardenaRateLimitError,
)

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    API_TYPE_AUTOMOWER,
    API_TYPE_GARDENA,
    CONF_API_TYPE,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_LOCATION_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class GardenaSmartSystemConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Gardena Smart System config flow.

    Step 1 — credentials: enter client_id + client_secret, validate.
    Step 2 — api_type: choose Gardena Smart System or Automower Connect.
    Step 3a — location: pick one of the user's gardens (Gardena only).
    Step 3b — (Automower) auto-creates entry with all discovered mowers.
    """

    VERSION = 2

    def __init__(self) -> None:
        """Initialize flow state."""
        self._client_id: str = ""
        self._client_secret: str = ""
        self._locations: list[dict[str, str]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the credentials step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            client_id = user_input[CONF_CLIENT_ID].strip()
            client_secret = user_input[CONF_CLIENT_SECRET].strip()

            session = async_get_clientsession(self.hass)
            auth = GardenaAuth(client_id, client_secret, session)
            try:
                await auth.async_ensure_valid_token()
            except GardenaAuthenticationError:
                errors["base"] = "invalid_auth"
            except GardenaRateLimitError:
                errors["base"] = "rate_limited"
            except GardenaConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during credential test")
                errors["base"] = "unknown"
            else:
                self._client_id = client_id
                self._client_secret = client_secret
                return await self.async_step_api_type()
            finally:
                await auth.async_revoke_token()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLIENT_ID): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_CLIENT_SECRET): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_api_type(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose which API to connect."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_type = user_input[CONF_API_TYPE]

            if api_type == API_TYPE_GARDENA:
                # Validate Gardena API access and get locations
                session = async_get_clientsession(self.hass)
                locations, error = await self._async_test_gardena(
                    session, self._client_id, self._client_secret
                )
                if error:
                    errors["base"] = error
                else:
                    self._locations = locations
                    if len(locations) == 1:
                        return self._async_create_gardena_entry(locations[0]["id"])
                    return await self.async_step_location()

            elif api_type == API_TYPE_AUTOMOWER:
                # Validate Automower API access
                session = async_get_clientsession(self.hass)
                error = await self._async_test_automower(
                    session, self._client_id, self._client_secret
                )
                if error:
                    errors["base"] = error
                else:
                    return self._async_create_automower_entry()

        options = [
            SelectOptionDict(value=API_TYPE_GARDENA, label="Gardena Smart System"),
            SelectOptionDict(value=API_TYPE_AUTOMOWER, label="Automower Connect"),
        ]
        return self.async_show_form(
            step_id="api_type",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_TYPE): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle location selection when the account has multiple gardens."""
        if user_input is not None:
            return self._async_create_gardena_entry(user_input[CONF_LOCATION_ID])

        options = [
            SelectOptionDict(value=loc["id"], label=loc["name"])
            for loc in self._locations
        ]
        return self.async_show_form(
            step_id="location",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOCATION_ID): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when the token is no longer valid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-authentication with new credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            client_id = user_input[CONF_CLIENT_ID].strip()
            client_secret = user_input[CONF_CLIENT_SECRET].strip()
            session = async_get_clientsession(self.hass)

            entry = self._get_reauth_entry()
            api_type = entry.data.get(CONF_API_TYPE, API_TYPE_GARDENA)

            if api_type == API_TYPE_AUTOMOWER:
                error = await self._async_test_automower(
                    session, client_id, client_secret
                )
            else:
                _, error = await self._async_test_gardena(
                    session, client_id, client_secret
                )

            if not error:
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **entry.data,
                        CONF_CLIENT_ID: client_id,
                        CONF_CLIENT_SECRET: client_secret,
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLIENT_ID): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_CLIENT_SECRET): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow changing credentials for an existing entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            client_id = user_input[CONF_CLIENT_ID].strip()
            client_secret = user_input[CONF_CLIENT_SECRET].strip()
            session = async_get_clientsession(self.hass)

            entry = self._get_reconfigure_entry()
            api_type = entry.data.get(CONF_API_TYPE, API_TYPE_GARDENA)

            if api_type == API_TYPE_AUTOMOWER:
                error = await self._async_test_automower(
                    session, client_id, client_secret
                )
            else:
                _, error = await self._async_test_gardena(
                    session, client_id, client_secret
                )

            if not error:
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **entry.data,
                        CONF_CLIENT_ID: client_id,
                        CONF_CLIENT_SECRET: client_secret,
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLIENT_ID): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_CLIENT_SECRET): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    # ── Entry creation helpers ─────────────────────────────────────

    def _async_create_gardena_entry(self, location_id: str) -> ConfigFlowResult:
        """Create a Gardena config entry."""
        self._async_abort_entries_match(
            {
                CONF_CLIENT_ID: self._client_id,
                CONF_API_TYPE: API_TYPE_GARDENA,
                CONF_LOCATION_ID: location_id,
            }
        )
        location_name = next(
            (loc["name"] for loc in self._locations if loc["id"] == location_id),
            location_id,
        )
        return self.async_create_entry(
            title=location_name,
            data={
                CONF_CLIENT_ID: self._client_id,
                CONF_CLIENT_SECRET: self._client_secret,
                CONF_LOCATION_ID: location_id,
                CONF_API_TYPE: API_TYPE_GARDENA,
            },
        )

    def _async_create_automower_entry(self) -> ConfigFlowResult:
        """Create an Automower config entry."""
        self._async_abort_entries_match(
            {
                CONF_CLIENT_ID: self._client_id,
                CONF_API_TYPE: API_TYPE_AUTOMOWER,
            }
        )
        return self.async_create_entry(
            title="Automower Connect",
            data={
                CONF_CLIENT_ID: self._client_id,
                CONF_CLIENT_SECRET: self._client_secret,
                CONF_API_TYPE: API_TYPE_AUTOMOWER,
            },
        )

    # ── Credential testing ─────────────────────────────────────────

    @staticmethod
    async def _async_test_gardena(
        session: aiohttp.ClientSession,
        client_id: str,
        client_secret: str,
    ) -> tuple[list[dict[str, str]], str]:
        """Test Gardena API access and return (locations, error_key)."""
        auth = GardenaAuth(client_id, client_secret, session)
        client = GardenaClient(auth, session)
        try:
            locations = await client.async_get_locations()
            return (
                [{"id": loc.location_id, "name": loc.name} for loc in locations],
                "",
            )
        except GardenaAuthenticationError:
            return [], "invalid_auth"
        except GardenaForbiddenError:
            return [], "forbidden"
        except GardenaRateLimitError:
            return [], "rate_limited"
        except GardenaConnectionError:
            return [], "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error during Gardena credential test")
            return [], "unknown"

    @staticmethod
    async def _async_test_automower(
        session: aiohttp.ClientSession,
        client_id: str,
        client_secret: str,
    ) -> str:
        """Test Automower API access. Returns error key or empty string."""
        auth = GardenaAuth(client_id, client_secret, session)
        client = AutomowerClient(auth, session)
        try:
            await client.async_get_mowers()
            return ""
        except AutomowerAuthenticationError:
            return "invalid_auth"
        except AutomowerForbiddenError:
            return "automower_not_connected"
        except AutomowerRateLimitError:
            return "rate_limited"
        except AutomowerConnectionError:
            return "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error during Automower credential test")
            return "unknown"
