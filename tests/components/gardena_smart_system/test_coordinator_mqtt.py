"""Tests for GardenaCoordinator MQTT command handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,  # type: ignore[no-redef]
    )

from custom_components.gardena_smart_system.const import DOMAIN

from .conftest import ENTRY_DATA, make_mock_device

_PATCH_CLIENT = "custom_components.gardena_smart_system.coordinator.GardenaClient"
_PATCH_AUTH = "custom_components.gardena_smart_system.coordinator.GardenaAuth"
_PATCH_WS = "custom_components.gardena_smart_system.coordinator.GardenaWebSocket"


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, title="My Garden")


@pytest.fixture
async def coordinator(hass: HomeAssistant, mock_config_entry: MockConfigEntry):
    """Set up the integration and return (coordinator, mock_client)."""
    devices = {d.device_id: d for d in [make_mock_device()]}
    mock_auth = AsyncMock()
    mock_auth.is_token_valid = True

    mock_client = AsyncMock()
    mock_client.async_get_devices = AsyncMock(return_value=devices)
    mock_client.async_get_websocket_url = AsyncMock(return_value="wss://test")
    mock_client.async_send_command = AsyncMock()

    mock_ws = AsyncMock()
    mock_ws.async_connect = AsyncMock()
    mock_ws.async_disconnect = AsyncMock()
    mock_ws.last_message_time = 0

    with (
        patch(_PATCH_CLIENT, return_value=mock_client),
        patch(_PATCH_AUTH, return_value=mock_auth),
        patch(_PATCH_WS, return_value=mock_ws),
    ):
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        coord = mock_config_entry.runtime_data
        # Reset throttle so tests don't interfere with each other
        coord._last_command_time = 0.0
        yield coord, mock_client


class TestMqttCommandHandler:
    """Tests for _async_handle_mqtt_command in GardenaCoordinator."""

    async def test_start_watering_default_duration(self, coordinator) -> None:
        coord, client = coordinator
        await coord._async_handle_mqtt_command("dev-1", {"action": "start_watering"})
        client.async_send_command.assert_called_once_with(
            "dev-1", "VALVE_CONTROL", "START_SECONDS_TO_OVERRIDE", seconds=3600
        )

    async def test_start_watering_custom_duration(self, coordinator) -> None:
        coord, client = coordinator
        await coord._async_handle_mqtt_command(
            "dev-1", {"action": "start_watering", "duration": 30}
        )
        client.async_send_command.assert_called_once_with(
            "dev-1", "VALVE_CONTROL", "START_SECONDS_TO_OVERRIDE", seconds=1800
        )

    async def test_start_watering_with_service_id(self, coordinator) -> None:
        coord, client = coordinator
        await coord._async_handle_mqtt_command(
            "dev-1", {"action": "start_watering", "service_id": "dev-1:2", "duration": 10}
        )
        client.async_send_command.assert_called_once_with(
            "dev-1:2", "VALVE_CONTROL", "START_SECONDS_TO_OVERRIDE", seconds=600
        )

    async def test_stop_watering(self, coordinator) -> None:
        coord, client = coordinator
        await coord._async_handle_mqtt_command("dev-1", {"action": "stop_watering"})
        client.async_send_command.assert_called_once_with(
            "dev-1", "VALVE_CONTROL", "STOP_UNTIL_NEXT_TASK"
        )

    async def test_turn_on_default_duration(self, coordinator) -> None:
        coord, client = coordinator
        await coord._async_handle_mqtt_command("dev-1", {"action": "turn_on"})
        client.async_send_command.assert_called_once_with(
            "dev-1", "POWER_SOCKET_CONTROL", "START_SECONDS_TO_OVERRIDE", seconds=3600
        )

    async def test_turn_on_custom_duration(self, coordinator) -> None:
        coord, client = coordinator
        await coord._async_handle_mqtt_command("dev-1", {"action": "turn_on", "duration": 120})
        client.async_send_command.assert_called_once_with(
            "dev-1", "POWER_SOCKET_CONTROL", "START_SECONDS_TO_OVERRIDE", seconds=7200
        )

    async def test_turn_off(self, coordinator) -> None:
        coord, client = coordinator
        await coord._async_handle_mqtt_command("dev-1", {"action": "turn_off"})
        client.async_send_command.assert_called_once_with(
            "dev-1", "POWER_SOCKET_CONTROL", "STOP_UNTIL_NEXT_TASK"
        )

    async def test_park(self, coordinator) -> None:
        coord, client = coordinator
        await coord._async_handle_mqtt_command("dev-1", {"action": "park"})
        client.async_send_command.assert_called_once_with(
            "dev-1", "MOWER_CONTROL", "PARK_UNTIL_FURTHER_NOTICE"
        )

    async def test_resume(self, coordinator) -> None:
        coord, client = coordinator
        await coord._async_handle_mqtt_command("dev-1", {"action": "resume"})
        client.async_send_command.assert_called_once_with(
            "dev-1", "MOWER_CONTROL", "START_DONT_OVERRIDE"
        )

    async def test_unknown_action_ignored(self, coordinator) -> None:
        coord, client = coordinator
        await coord._async_handle_mqtt_command("dev-1", {"action": "explode"})
        client.async_send_command.assert_not_called()

    async def test_missing_action_ignored(self, coordinator) -> None:
        coord, client = coordinator
        await coord._async_handle_mqtt_command("dev-1", {})
        client.async_send_command.assert_not_called()

    async def test_command_throttled(self, coordinator) -> None:
        """After the token bucket is drained, further commands are throttled."""
        import time

        from custom_components.gardena_smart_system.const import COMMAND_BURST_CAPACITY

        coord, client = coordinator
        # Drain the bucket by zeroing all tokens.
        coord._command_tokens = 0.0
        coord._command_tokens_updated = time.monotonic()
        await coord._async_handle_mqtt_command("dev-1", {"action": "park"})
        # Should be throttled — no API call
        client.async_send_command.assert_not_called()
        # Sanity: refilling the bucket lets the next command through.
        coord._command_tokens = float(COMMAND_BURST_CAPACITY)
        await coord._async_handle_mqtt_command("dev-1", {"action": "park"})
        client.async_send_command.assert_called_once()

    async def test_command_exception_logged_not_raised(self, coordinator) -> None:
        """If async_send_command raises, it's logged but doesn't propagate."""
        coord, client = coordinator
        client.async_send_command.side_effect = Exception("API error")
        # Should not raise
        await coord._async_handle_mqtt_command("dev-1", {"action": "park"})
        client.async_send_command.assert_called_once()
