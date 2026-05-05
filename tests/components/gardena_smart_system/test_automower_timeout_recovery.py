"""Tests for the Automower path of issue #22 timeout recovery."""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from aioautomower.const import MowerActivity
from aioautomower.exceptions import AutomowerConnectionError
from aioautomower.models import AutomowerDevice
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,  # type: ignore[no-redef]
    )

from custom_components.gardena_smart_system.const import (
    DOMAIN,
    OPT_AUTO_RETRY_ON_TIMEOUT,
)

from .test_automower import AUTOMOWER_ENTRY_DATA, make_mock_automower_device

_PATCH_AM_CLIENT = "custom_components.gardena_smart_system.automower_coordinator.AutomowerClient"
_PATCH_AM_AUTH = "custom_components.gardena_smart_system.automower_coordinator.GardenaAuth"
_PATCH_AM_WS = "custom_components.gardena_smart_system.automower_coordinator.AutomowerWebSocket"


@asynccontextmanager
async def _setup_automower(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    devices: dict[str, AutomowerDevice],
) -> AsyncGenerator[AsyncMock]:
    """Set up the integration with Automower devices and yield the mock client."""
    with (
        patch(_PATCH_AM_CLIENT) as mock_client_cls,
        patch(_PATCH_AM_AUTH, return_value=AsyncMock()),
        patch(_PATCH_AM_WS) as mock_ws_cls,
    ):
        mock_client = AsyncMock()
        mock_client.async_get_mowers = AsyncMock(return_value=devices)
        mock_client.async_start = AsyncMock()
        mock_client_cls.return_value = mock_client

        mock_ws = AsyncMock()
        mock_ws.async_connect = AsyncMock()
        mock_ws.async_disconnect = AsyncMock()
        mock_ws_cls.return_value = mock_ws

        config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        yield mock_client


@pytest.fixture
def automower_config_entry() -> MockConfigEntry:
    """Return a MockConfigEntry for the Automower integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        data=AUTOMOWER_ENTRY_DATA,
        title="Automower",
        version=2,
    )


def _push_mowing_state(coordinator, device: AutomowerDevice) -> None:
    """Mutate the coordinator-cached AutomowerDevice into the MOWING activity."""
    new_mower = dataclasses.replace(device.mower, activity=MowerActivity.MOWING)
    new_device = dataclasses.replace(device, mower=new_mower)
    coordinator.async_set_updated_data({device.mower_id: new_device})


class TestAutomowerTimeoutRecovery:
    """Mirror of the Gardena recovery tests for the Automower path."""

    async def test_recovery_when_state_reaches_target(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """Connection error but device reached MOWING — error is suppressed."""
        device = make_mock_automower_device(mower_activity=MowerActivity.PARKED_IN_CS)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            coordinator = automower_config_entry.runtime_data

            def _side_effect(*_args: Any, **_kwargs: Any) -> None:
                _push_mowing_state(coordinator, device)
                raise AutomowerConnectionError("Timeout")

            mock_client.async_start.side_effect = _side_effect

            await hass.services.async_call(
                "lawn_mower",
                "start_mowing",
                {"entity_id": "lawn_mower.test_mower_mower"},
                blocking=True,
            )

            assert mock_client.async_start.call_count == 1

    async def test_no_recovery_no_retry_raises_command_timeout(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """No state change + retry disabled → command_timeout, no second call."""
        device = make_mock_automower_device(mower_activity=MowerActivity.PARKED_IN_CS)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            mock_client.async_start.side_effect = AutomowerConnectionError("Timeout")

            with pytest.raises(HomeAssistantError) as exc_info:
                await hass.services.async_call(
                    "lawn_mower",
                    "start_mowing",
                    {"entity_id": "lawn_mower.test_mower_mower"},
                    blocking=True,
                )

            assert exc_info.value.translation_key == "command_timeout"
            assert mock_client.async_start.call_count == 1

    async def test_retry_succeeds_when_second_call_lands(
        self, hass: HomeAssistant, automower_config_entry: MockConfigEntry
    ) -> None:
        """First call times out, second call returns cleanly and state arrives."""
        device = make_mock_automower_device(mower_activity=MowerActivity.PARKED_IN_CS)
        devices = {device.mower_id: device}

        async with _setup_automower(hass, automower_config_entry, devices) as mock_client:
            hass.config_entries.async_update_entry(
                automower_config_entry,
                options={
                    **automower_config_entry.options,
                    OPT_AUTO_RETRY_ON_TIMEOUT: True,
                },
            )
            await hass.async_block_till_done()

            coordinator = automower_config_entry.runtime_data
            calls: list[int] = []

            def _side_effect(*_args: Any, **_kwargs: Any) -> None:
                calls.append(1)
                if len(calls) == 1:
                    raise AutomowerConnectionError("Timeout")
                _push_mowing_state(coordinator, device)

            mock_client.async_start.side_effect = _side_effect

            await hass.services.async_call(
                "lawn_mower",
                "start_mowing",
                {"entity_id": "lawn_mower.test_mower_mower"},
                blocking=True,
            )

            assert mock_client.async_start.call_count == 2
