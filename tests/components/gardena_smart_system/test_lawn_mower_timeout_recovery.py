"""Tests for the issue #22 poll-after-timeout / opt-in retry recovery path."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.gardena_smart_system.const import OPT_AUTO_RETRY_ON_TIMEOUT

from .conftest import make_mock_device

_PATCH_CLIENT = "custom_components.gardena_smart_system.coordinator.GardenaClient"
_PATCH_AUTH = "custom_components.gardena_smart_system.coordinator.GardenaAuth"
_PATCH_WS = "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"


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

    Simulates the real-world race the recovery path was designed for: the
    Gardena cloud accepted the command and pushed the activity update via
    WebSocket, but the HTTP response itself did not arrive in time.
    """

    def _side_effect(*_args: Any, **_kwargs: Any) -> None:
        device.mower.activity = target_activity
        coordinator.async_set_updated_data({device.device_id: device})
        raise exc

    return _side_effect


class TestTimeoutRecovery:
    """Issue #22 Feature 1: poll-after-timeout."""

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

    async def test_no_recovery_no_retry_raises_command_timeout(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """No state change + retry disabled → command_timeout error, no second call."""
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
            assert mock_client.async_send_command.call_count == 1


class TestTimeoutRetry:
    """Issue #22 Feature 2: opt-in auto-retry."""

    async def test_retry_succeeds_when_second_call_lands(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """First call times out, second call returns cleanly and state arrives."""
        from aiogardenasmart.exceptions import GardenaConnectionError

        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            hass.config_entries.async_update_entry(
                mock_config_entry,
                options={**mock_config_entry.options, OPT_AUTO_RETRY_ON_TIMEOUT: True},
            )
            await hass.async_block_till_done()

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

    async def test_retry_disabled_does_not_call_twice(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Retry must stay opt-in — without the option, no second call is made."""
        from aiogardenasmart.exceptions import GardenaConnectionError

        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            mock_client.async_send_command.side_effect = GardenaConnectionError("Timeout")

            with pytest.raises(HomeAssistantError):
                await hass.services.async_call(
                    "lawn_mower",
                    "start_mowing",
                    {"entity_id": "lawn_mower.my_sensor_mower"},
                    blocking=True,
                )

            assert mock_client.async_send_command.call_count == 1

    async def test_retry_enabled_but_still_no_state_change_raises_timeout(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Retry succeeds at the API level but the device never confirms the state."""
        from aiogardenasmart.exceptions import GardenaConnectionError

        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            hass.config_entries.async_update_entry(
                mock_config_entry,
                options={**mock_config_entry.options, OPT_AUTO_RETRY_ON_TIMEOUT: True},
            )
            await hass.async_block_till_done()

            calls: list[int] = []

            def _side_effect(*_args: Any, **_kwargs: Any) -> None:
                calls.append(1)
                if len(calls) == 1:
                    raise GardenaConnectionError("Timeout")
                # Second call returns cleanly but device state never changes.

            mock_client.async_send_command.side_effect = _side_effect

            with pytest.raises(HomeAssistantError) as exc_info:
                await hass.services.async_call(
                    "lawn_mower",
                    "start_mowing",
                    {"entity_id": "lawn_mower.my_sensor_mower"},
                    blocking=True,
                )

            assert exc_info.value.translation_key == "command_timeout"
            assert mock_client.async_send_command.call_count == 2

    async def test_retry_second_call_fails_too(
        self, hass: HomeAssistant, mock_config_entry: object
    ) -> None:
        """Both calls fail — exactly two API calls, then a translated error."""
        from aiogardenasmart.exceptions import GardenaConnectionError

        device = make_mock_device(has_sensor=False, has_mower=True)
        devices = {device.device_id: device}

        async for mock_client in _setup_with_devices(hass, mock_config_entry, devices):
            hass.config_entries.async_update_entry(
                mock_config_entry,
                options={**mock_config_entry.options, OPT_AUTO_RETRY_ON_TIMEOUT: True},
            )
            await hass.async_block_till_done()

            mock_client.async_send_command.side_effect = GardenaConnectionError("Timeout")

            with pytest.raises(HomeAssistantError) as exc_info:
                await hass.services.async_call(
                    "lawn_mower",
                    "start_mowing",
                    {"entity_id": "lawn_mower.my_sensor_mower"},
                    blocking=True,
                )

            assert exc_info.value.translation_key == "command_timeout"
            assert mock_client.async_send_command.call_count == 2
