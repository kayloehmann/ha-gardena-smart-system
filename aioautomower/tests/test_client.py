"""Contract tests for AutomowerClient REST API methods."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import aiohttp
import pytest
from aiogardenasmart.auth import GardenaAuth
from aiogardenasmart.const import AUTH_TOKEN_URL
from aioresponses import aioresponses

from aioautomower.client import AutomowerClient
from aioautomower.const import API_BASE_URL, ActionType
from aioautomower.exceptions import (
    AutomowerAuthenticationError,
    AutomowerConnectionError,
    AutomowerForbiddenError,
    AutomowerRateLimitError,
    AutomowerRequestError,
)

from .fixtures import (
    MOWER_ID,
    MOWER_RESPONSE,
    MOWERS_RESPONSE,
    STAY_OUT_ZONE_ID,
    TOKEN_RESPONSE,
    WORK_AREA_ID,
)


@pytest.fixture
async def authenticated_client() -> AsyncGenerator[
    tuple[AutomowerClient, aiohttp.ClientSession], None
]:
    """Return an AutomowerClient with a pre-acquired token."""
    async with aiohttp.ClientSession() as session:
        auth = GardenaAuth("client-id", "secret", session)
        client = AutomowerClient(auth, session)

        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, payload=TOKEN_RESPONSE)
            await auth.async_ensure_valid_token()

        yield client, session


class TestGetMowers:
    async def test_returns_mowers(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/mowers", payload=MOWERS_RESPONSE)
            mowers = await client.async_get_mowers()

        assert MOWER_ID in mowers
        assert mowers[MOWER_ID].name == "Test Automower 420"
        assert mowers[MOWER_ID].battery.level == 75

    async def test_returns_empty_dict_when_no_mowers(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/mowers", payload={"data": []})
            mowers = await client.async_get_mowers()

        assert mowers == {}


class TestGetMower:
    async def test_returns_single_mower(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/mowers/{MOWER_ID}", payload=MOWER_RESPONSE)
            mower = await client.async_get_mower(MOWER_ID)

        assert mower.mower_id == MOWER_ID
        assert mower.system.serial_number == "SN-AM-001"

    async def test_mower_work_areas_parsed(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/mowers/{MOWER_ID}", payload=MOWER_RESPONSE)
            mower = await client.async_get_mower(MOWER_ID)

        assert WORK_AREA_ID in mower.work_areas
        assert mower.work_areas[WORK_AREA_ID].name == "Front Lawn"
        assert mower.work_areas[WORK_AREA_ID].cutting_height == 50

    async def test_mower_stay_out_zones_parsed(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/mowers/{MOWER_ID}", payload=MOWER_RESPONSE)
            mower = await client.async_get_mower(MOWER_ID)

        assert STAY_OUT_ZONE_ID in mower.stay_out_zones
        assert mower.stay_out_zones[STAY_OUT_ZONE_ID].name == "Flower Bed"


class TestActions:
    async def test_start_sends_correct_action_type(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        """Contract test: Start action must use 'Start' as type (not 'START' or 'start')."""
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/actions"
        with aioresponses() as m:
            m.post(url, status=202, payload={})
            await client.async_start(MOWER_ID)

        sent_body = m.requests[("POST", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["type"] == ActionType.START

    async def test_start_with_duration_includes_attributes(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        """Contract test: Start with duration must include attributes.duration in payload."""
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/actions"
        with aioresponses() as m:
            m.post(url, status=202, payload={})
            await client.async_start(MOWER_ID, duration=90)

        sent_body = m.requests[("POST", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["attributes"]["duration"] == 90

    async def test_pause_sends_correct_action_type(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/actions"
        with aioresponses() as m:
            m.post(url, status=202, payload={})
            await client.async_pause(MOWER_ID)

        sent_body = m.requests[("POST", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["type"] == ActionType.PAUSE

    async def test_park_until_next_schedule(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/actions"
        with aioresponses() as m:
            m.post(url, status=202, payload={})
            await client.async_park_until_next_schedule(MOWER_ID)

        sent_body = m.requests[("POST", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["type"] == ActionType.PARK_UNTIL_NEXT_SCHEDULE

    async def test_park_until_further_notice(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/actions"
        with aioresponses() as m:
            m.post(url, status=202, payload={})
            await client.async_park_until_further_notice(MOWER_ID)

        sent_body = m.requests[("POST", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["type"] == ActionType.PARK_UNTIL_FURTHER_NOTICE

    async def test_resume_schedule(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/actions"
        with aioresponses() as m:
            m.post(url, status=202, payload={})
            await client.async_resume_schedule(MOWER_ID)

        sent_body = m.requests[("POST", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["type"] == ActionType.RESUME_SCHEDULE

    async def test_confirm_error(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/actions"
        with aioresponses() as m:
            m.post(url, status=202, payload={})
            await client.async_confirm_error(MOWER_ID)

        sent_body = m.requests[("POST", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["type"] == ActionType.CONFIRM_ERROR

    async def test_content_type_header_is_json_api(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        """Contract test: POST /actions must use application/vnd.api+json Content-Type without charset."""
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/actions"
        with aioresponses() as m:
            m.post(url, status=202, payload={})
            await client.async_pause(MOWER_ID)

        sent_headers = m.requests[("POST", aiohttp.client.URL(url))][0].kwargs["headers"]
        content_type = sent_headers.get("Content-Type", "")
        assert content_type == "application/vnd.api+json", (
            f"Expected 'application/vnd.api+json', got {content_type!r}. "
            "A charset suffix causes request failures with the Husqvarna API."
        )

    async def test_start_without_duration_has_no_attributes(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        """Contract test: Start without duration must NOT include attributes key."""
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/actions"
        with aioresponses() as m:
            m.post(url, status=202, payload={})
            await client.async_start(MOWER_ID, duration=None)

        sent_body = m.requests[("POST", aiohttp.client.URL(url))][0].kwargs["json"]
        assert "attributes" not in sent_body["data"]


class TestSettings:
    async def test_set_cutting_height_payload(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        """Contract test: PATCH /settings must send cuttingHeight in attributes."""
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/settings"
        with aioresponses() as m:
            m.patch(url, status=204, payload={})
            await client.async_set_cutting_height(MOWER_ID, 7)

        sent_body = m.requests[("PATCH", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["type"] == "settings"
        assert sent_body["data"]["attributes"]["cuttingHeight"] == 7

    async def test_set_headlight_mode_payload(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        """Contract test: PATCH /settings must wrap headlight mode in headlight.mode."""
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/settings"
        with aioresponses() as m:
            m.patch(url, status=204, payload={})
            await client.async_set_headlight_mode(MOWER_ID, "ALWAYS_ON")

        sent_body = m.requests[("PATCH", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["attributes"]["headlight"]["mode"] == "ALWAYS_ON"


class TestCalendar:
    async def test_update_calendar_payload(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        """Contract test: PATCH /calendar must wrap tasks in data.attributes.tasks."""
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/calendar"
        tasks = [
            {
                "start": 480,
                "duration": 120,
                "monday": True,
                "tuesday": False,
                "wednesday": True,
                "thursday": False,
                "friday": True,
                "saturday": False,
                "sunday": False,
            }
        ]
        with aioresponses() as m:
            m.patch(url, status=204, payload={})
            await client.async_update_calendar(MOWER_ID, tasks)

        sent_body = m.requests[("PATCH", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["type"] == "calendar"
        assert sent_body["data"]["attributes"]["tasks"] == tasks

    async def test_update_calendar_empty_tasks(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/calendar"
        with aioresponses() as m:
            m.patch(url, status=204, payload={})
            await client.async_update_calendar(MOWER_ID, [])

        sent_body = m.requests[("PATCH", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["attributes"]["tasks"] == []


class TestWorkAreas:
    async def test_set_work_area_cutting_height_payload(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        """Contract test: PATCH /workAreas/{id} must include work_area_id as data.id (string)."""
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/workAreas/{WORK_AREA_ID}"
        with aioresponses() as m:
            m.patch(url, status=204, payload={})
            await client.async_set_work_area_cutting_height(MOWER_ID, WORK_AREA_ID, 60)

        sent_body = m.requests[("PATCH", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["type"] == "workArea"
        assert sent_body["data"]["id"] == str(WORK_AREA_ID)
        assert sent_body["data"]["attributes"]["cuttingHeight"] == 60

    async def test_set_work_area_enabled_true(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        """Contract test: PATCH /workAreas/{id} to enable a work area."""
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/workAreas/{WORK_AREA_ID}"
        with aioresponses() as m:
            m.patch(url, status=204, payload={})
            await client.async_set_work_area_enabled(MOWER_ID, WORK_AREA_ID, True)

        sent_body = m.requests[("PATCH", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["attributes"]["enabled"] is True

    async def test_set_work_area_enabled_false(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/workAreas/{WORK_AREA_ID}"
        with aioresponses() as m:
            m.patch(url, status=204, payload={})
            await client.async_set_work_area_enabled(MOWER_ID, WORK_AREA_ID, False)

        sent_body = m.requests[("PATCH", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["attributes"]["enabled"] is False


class TestStayOutZones:
    async def test_enable_stay_out_zone_payload(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        """Contract test: PATCH /stayOutZones/{id} uses 'enable' (not 'enabled') as key."""
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/stayOutZones/{STAY_OUT_ZONE_ID}"
        with aioresponses() as m:
            m.patch(url, status=204, payload={})
            await client.async_set_stay_out_zone(MOWER_ID, STAY_OUT_ZONE_ID, True)

        sent_body = m.requests[("PATCH", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["type"] == "stayOutZone"
        assert sent_body["data"]["id"] == STAY_OUT_ZONE_ID
        assert sent_body["data"]["attributes"]["enable"] is True, (
            "Husqvarna API uses 'enable' (not 'enabled') for stay-out zone toggle"
        )

    async def test_disable_stay_out_zone(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        url = f"{API_BASE_URL}/mowers/{MOWER_ID}/stayOutZones/{STAY_OUT_ZONE_ID}"
        with aioresponses() as m:
            m.patch(url, status=204, payload={})
            await client.async_set_stay_out_zone(MOWER_ID, STAY_OUT_ZONE_ID, False)

        sent_body = m.requests[("PATCH", aiohttp.client.URL(url))][0].kwargs["json"]
        assert sent_body["data"]["attributes"]["enable"] is False


class TestErrorHandling:
    async def test_401_raises_auth_error(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/mowers", status=401, payload={})
            with pytest.raises(AutomowerAuthenticationError):
                await client.async_get_mowers()

    async def test_403_raises_forbidden_error(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/mowers", status=403, payload={})
            with pytest.raises(AutomowerForbiddenError):
                await client.async_get_mowers()

    async def test_429_raises_rate_limit_error(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        """Contract test: 429 must raise AutomowerRateLimitError, not a generic error.

        The Husqvarna API returns 429 for rate limiting. This is distinct from
        auth errors and must be handled separately so callers can implement backoff.
        """
        client, _session = authenticated_client
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/mowers", status=429, payload={})
            with pytest.raises(AutomowerRateLimitError):
                await client.async_get_mowers()

    async def test_500_raises_request_error(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/mowers", status=500, body="Internal Error")
            with pytest.raises(AutomowerRequestError) as exc_info:
                await client.async_get_mowers()
        assert exc_info.value.status == 500

    async def test_network_error_raises_connection_error(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        with aioresponses() as m:
            m.get(
                f"{API_BASE_URL}/mowers",
                exception=aiohttp.ClientConnectionError("Connection refused"),
            )
            with pytest.raises(AutomowerConnectionError):
                await client.async_get_mowers()

    async def test_202_returns_empty_dict(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        with aioresponses() as m:
            m.post(f"{API_BASE_URL}/mowers/{MOWER_ID}/actions", status=202, body="")
            # Should not raise
            await client.async_pause(MOWER_ID)

    async def test_204_returns_empty_dict(
        self, authenticated_client: tuple[AutomowerClient, aiohttp.ClientSession]
    ) -> None:
        client, _session = authenticated_client
        with aioresponses() as m:
            m.patch(f"{API_BASE_URL}/mowers/{MOWER_ID}/settings", status=204, body="")
            # Should not raise
            await client.async_set_cutting_height(MOWER_ID, 5)
