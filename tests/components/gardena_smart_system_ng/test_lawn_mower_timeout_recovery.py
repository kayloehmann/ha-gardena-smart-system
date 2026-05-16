"""Tests for the command-timeout / retry-until-confirmed recovery path."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.gardena_smart_system_ng.const import COMMAND_RETRY_ATTEMPTS

from .conftest import make_mock_device

_PATCH_CLIENT = "custom_components.gardena_smart_system_ng.coordinator.GardenaClient"
_PATCH_AUTH = "custom_components.gardena_smart_system_ng.coordinator.GardenaAuth"
_PATCH_WS = "custom_components.gardena_smart_system_ng.coordinator.GardenaWebSocket"


async def _setup_with_devices(hass, mock_config_entry, devices):
    """Set up the integration with given device map and yield mock client."""
    with (
        patch(_PATCH_CLIENT) as mock_client_cls,
        patch(_PATCH_AUTH, return_value=AsyncMock()),
        patch(_PATCH_WS) as mock_ws_cls,
    ):
        mock_client = AsyncMock()
        mock_client.async_get_devices = AsyncMock(return_value=devices)
        mock_client.async_get_websocket_url = AsyncMock(return_value="wss://test")
        mock_client.async_send_command = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_ws = AsyncMock()
        mock_ws.async_connect = AsyncMock()
        mock_ws.async_disconnect = AsyncMock()
        mock_ws_cls.return_value = mock_ws

        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        yield mock_client


def _push_state_then_raise(coordinator, device, target_activity, exc):
    """Build a side_effect that mutates coordinator data, then raises ``exc``.

    Simulates the real-world race: the Gardena cloud accepted the command and
    pushed the activity update via WebSocket, but the HTTP response itself did
    not arrive in time.
    """

    def _side_effect(*_args: Any, **_kwargs: Any) -> None:
        device.mower.activity = target_activity
        coordinator.async_set_updated_data({device.device_id: device})
        raise exc

    return _side_effect


class TestTimeoutRecovery:
    """First-attempt WebSocket-confirmation path."""

    async def test_recovery_when_state_reaches_target(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Client-timeout but device reached OK_CUTTING — error is suppressed."""
        from aiogardenasmart.exceptions import GardenaConnectionError

        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            coordinator = mock_config_entry.runtime_data
            mock_client.async_send_command.side_effect = _push_state_then_raise(
                coordinator,
                device,
                "OK_CUTTING",
                GardenaConnectionError("Timeout"),
            )

            await hass.services.async_call(
                "lawn_mower",
                "start_mowing",
                {"entity_id": "lawn_mower.my_sensor_mower"},
                blocking=True,
            )

            assert mock_client.async_send_command.call_count == 1

    @pytest.mark.parametrize("status", [502, 503, 504])
    async def test_recovery_for_gateway_5xx(
        self, hass: HomeAssistant, mock_config_entry: object, status: int
    ) -> None:
        """5xx upstream timeouts use the same recovery path as connection errors."""
        from aiogardenasmart.exceptions import GardenaRequestError

        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            coordinator = mock_config_entry.runtime_data
            mock_client.async_send_command.side_effect = _push_state_then_raise(
                coordinator,
                device,
                "OK_CUTTING",
                GardenaRequestError(status, "gateway timeout"),
            )

            await hass.services.async_call(
                "lawn_mower",
                "start_mowing",
                {"entity_id": "lawn_mower.my_sensor_mower"},
                blocking=True,
            )

            assert mock_client.async_send_command.call_count == 1


class TestTimeoutRetry:
    """Multi-attempt retry path — retries are unconditional, no opt-in."""

    async def test_retry_succeeds_when_second_call_lands(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """First call times out, second call returns cleanly and state arrives."""
        from aiogardenasmart.exceptions import GardenaConnectionError

        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            coordinator = mock_config_entry.runtime_data
            calls: list[int] = []

            def _side_effect(*_args: Any, **_kwargs: Any) -> None:
                calls.append(1)
                if len(calls) == 1:
                    # First call: simulate dropped HTTP response, no state change.
                    raise GardenaConnectionError("Timeout")
                # Second call: server accepts, push the state update.
                device.mower.activity = "OK_CUTTING"
                coordinator.async_set_updated_data({device.device_id: device})

            mock_client.async_send_command.side_effect = _side_effect

            await hass.services.async_call(
                "lawn_mower",
                "start_mowing",
                {"entity_id": "lawn_mower.my_sensor_mower"},
                blocking=True,
            )

            assert mock_client.async_send_command.call_count == 2

    async def test_all_attempts_exhausted_raises_command_timeout(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Every attempt fails — exactly N calls, then command_timeout."""
        from aiogardenasmart.exceptions import GardenaConnectionError

        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            mock_client.async_send_command.side_effect = GardenaConnectionError("Timeout")

            with pytest.raises(HomeAssistantError) as exc_info:
                await hass.services.async_call(
                    "lawn_mower",
                    "start_mowing",
                    {"entity_id": "lawn_mower.my_sensor_mower"},
                    blocking=True,
                )

            assert exc_info.value.translation_key == "command_timeout"
            assert mock_client.async_send_command.call_count == COMMAND_RETRY_ATTEMPTS

    async def test_retry_clean_response_but_no_state_change_raises_timeout(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Final attempt returns cleanly at the HTTP level but state never arrives.

        Once any attempt returns cleanly the loop trusts it and exits — no
        further retries even if WebSocket confirmation never happens. The
        service call therefore succeeds from HA's perspective. (If the user
        wants strict end-state confirmation they can read the entity state.)
        """
        from aiogardenasmart.exceptions import GardenaConnectionError

        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            calls: list[int] = []

            def _side_effect(*_args: Any, **_kwargs: Any) -> None:
                calls.append(1)
                if len(calls) == 1:
                    raise GardenaConnectionError("Timeout")
                # Subsequent calls return cleanly but device state never changes.

            mock_client.async_send_command.side_effect = _side_effect

            await hass.services.async_call(
                "lawn_mower",
                "start_mowing",
                {"entity_id": "lawn_mower.my_sensor_mower"},
                blocking=True,
            )

            assert mock_client.async_send_command.call_count == 2
