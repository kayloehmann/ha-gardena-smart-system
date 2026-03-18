"""Tests for GardenaClient REST API methods."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import aiohttp
import pytest
from aioresponses import aioresponses

from aiogardenasmart.auth import GardenaAuth
from aiogardenasmart.client import GardenaClient
from aiogardenasmart.const import API_BASE_URL, AUTH_TOKEN_URL
from aiogardenasmart.exceptions import (
    GardenaAuthenticationError,
    GardenaConnectionError,
    GardenaForbiddenError,
    GardenaRequestError,
)

from .fixtures import (
    IRRIGATION_DEVICE_ID,
    IRRIGATION_LOCATION_RESPONSE,
    LOCATION_ID,
    SENSOR_DEVICE_ID,
    SENSOR_LOCATION_RESPONSE,
    TOKEN_RESPONSE,
    WATER_CONTROL_DEVICE_ID,
    WATER_CONTROL_LOCATION_RESPONSE,
    WEBSOCKET_URL_RESPONSE,
)


@pytest.fixture
async def authenticated_client() -> AsyncGenerator[tuple[GardenaClient, aiohttp.ClientSession], None]:
    """Return a GardenaClient with a pre-acquired token."""
    async with aiohttp.ClientSession() as session:
        auth = GardenaAuth("client-id", "secret", session)
        client = GardenaClient(auth, session)

        with aioresponses() as m:
            m.post(AUTH_TOKEN_URL, payload=TOKEN_RESPONSE)
            await auth.async_ensure_valid_token()

        yield client, session


class TestGetLocations:
    async def test_returns_locations(
        self, authenticated_client: tuple[GardenaClient, aiohttp.ClientSession]
    ) -> None:
        client, session = authenticated_client
        payload = {
            "data": [
                {
                    "id": LOCATION_ID,
                    "type": "LOCATION",
                    "attributes": {"name": {"value": "My Garden"}},
                }
            ]
        }
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/locations", payload=payload)
            locations = await client.async_get_locations()

        assert len(locations) == 1
        assert locations[0].location_id == LOCATION_ID
        assert locations[0].name == "My Garden"

    async def test_empty_locations(
        self, authenticated_client: tuple[GardenaClient, aiohttp.ClientSession]
    ) -> None:
        client, session = authenticated_client
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/locations", payload={"data": []})
            locations = await client.async_get_locations()

        assert locations == []


class TestGetDevices:
    async def test_returns_sensor_device(
        self, authenticated_client: tuple[GardenaClient, aiohttp.ClientSession]
    ) -> None:
        client, session = authenticated_client
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/locations/{LOCATION_ID}", payload=SENSOR_LOCATION_RESPONSE)
            devices = await client.async_get_devices(LOCATION_ID)

        assert SENSOR_DEVICE_ID in devices
        assert devices[SENSOR_DEVICE_ID].sensor is not None

    async def test_returns_water_control_device(
        self, authenticated_client: tuple[GardenaClient, aiohttp.ClientSession]
    ) -> None:
        client, session = authenticated_client
        with aioresponses() as m:
            m.get(
                f"{API_BASE_URL}/locations/{LOCATION_ID}",
                payload=WATER_CONTROL_LOCATION_RESPONSE,
            )
            devices = await client.async_get_devices(LOCATION_ID)

        device = devices[WATER_CONTROL_DEVICE_ID]
        assert len(device.valves) == 1

    async def test_returns_irrigation_controller(
        self, authenticated_client: tuple[GardenaClient, aiohttp.ClientSession]
    ) -> None:
        client, session = authenticated_client
        with aioresponses() as m:
            m.get(
                f"{API_BASE_URL}/locations/{LOCATION_ID}",
                payload=IRRIGATION_LOCATION_RESPONSE,
            )
            devices = await client.async_get_devices(LOCATION_ID)

        assert len(devices[IRRIGATION_DEVICE_ID].valves) == 6


class TestGetWebSocketUrl:
    async def test_returns_ws_url(
        self, authenticated_client: tuple[GardenaClient, aiohttp.ClientSession]
    ) -> None:
        client, session = authenticated_client
        with aioresponses() as m:
            m.post(f"{API_BASE_URL}/websocket", payload=WEBSOCKET_URL_RESPONSE)
            url = await client.async_get_websocket_url(LOCATION_ID)

        assert url == "wss://ws.smart.gardena.dev/v1/test-ws-url"


class TestSendCommand:
    async def test_valve_open_command(
        self, authenticated_client: tuple[GardenaClient, aiohttp.ClientSession]
    ) -> None:
        client, session = authenticated_client
        service_id = f"{WATER_CONTROL_DEVICE_ID}:1"
        with aioresponses() as m:
            m.put(f"{API_BASE_URL}/command/{service_id}", status=202, payload={})
            await client.async_send_command(
                service_id=service_id,
                control_type="VALVE_CONTROL",
                command="START_SECONDS_TO_OVERRIDE",
                seconds=3600,
            )
        # No exception = success

    async def test_command_with_no_params(
        self, authenticated_client: tuple[GardenaClient, aiohttp.ClientSession]
    ) -> None:
        client, session = authenticated_client
        service_id = f"{WATER_CONTROL_DEVICE_ID}:1"
        with aioresponses() as m:
            m.put(f"{API_BASE_URL}/command/{service_id}", status=202, payload={})
            await client.async_send_command(
                service_id=service_id,
                control_type="VALVE_CONTROL",
                command="STOP_UNTIL_NEXT_TASK",
            )


class TestErrorHandling:
    async def test_401_raises_auth_error(
        self, authenticated_client: tuple[GardenaClient, aiohttp.ClientSession]
    ) -> None:
        client, session = authenticated_client
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/locations", status=401, payload={})
            with pytest.raises(GardenaAuthenticationError):
                await client.async_get_locations()

    async def test_403_raises_forbidden_error(
        self, authenticated_client: tuple[GardenaClient, aiohttp.ClientSession]
    ) -> None:
        client, session = authenticated_client
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/locations", status=403, payload={})
            with pytest.raises(GardenaForbiddenError):
                await client.async_get_locations()

    async def test_500_raises_request_error(
        self, authenticated_client: tuple[GardenaClient, aiohttp.ClientSession]
    ) -> None:
        client, session = authenticated_client
        with aioresponses() as m:
            m.get(f"{API_BASE_URL}/locations", status=500, body="Internal Error")
            with pytest.raises(GardenaRequestError) as exc_info:
                await client.async_get_locations()
        assert exc_info.value.status == 500

    async def test_network_error_raises_connection_error(
        self, authenticated_client: tuple[GardenaClient, aiohttp.ClientSession]
    ) -> None:
        client, session = authenticated_client
        with aioresponses() as m:
            m.get(
                f"{API_BASE_URL}/locations",
                exception=aiohttp.ClientConnectionError("Connection refused"),
            )
            with pytest.raises(GardenaConnectionError):
                await client.async_get_locations()

    async def test_204_returns_empty_dict(
        self, authenticated_client: tuple[GardenaClient, aiohttp.ClientSession]
    ) -> None:
        client, session = authenticated_client
        service_id = f"{WATER_CONTROL_DEVICE_ID}:1"
        with aioresponses() as m:
            m.put(f"{API_BASE_URL}/command/{service_id}", status=204, body="")
            # Should not raise
            await client.async_send_command(
                service_id=service_id,
                control_type="VALVE_CONTROL",
                command="STOP_UNTIL_NEXT_TASK",
            )
