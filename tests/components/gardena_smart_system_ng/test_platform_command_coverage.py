"""Coverage for platform command internals (expected-state probes, optimistic state)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,  # type: ignore[no-redef]
    )

from custom_components.gardena_smart_system_ng import entity as entity_mod
from custom_components.gardena_smart_system_ng import gardena_event as event_mod
from custom_components.gardena_smart_system_ng.const import CONF_API_TYPE, DOMAIN
from custom_components.gardena_smart_system_ng.coordinator import GardenaCoordinator
from custom_components.gardena_smart_system_ng.gardena_event import GardenaValveEventEntity
from custom_components.gardena_smart_system_ng.lawn_mower import GardenaLawnMowerEntity
from custom_components.gardena_smart_system_ng.switch import GardenaPowerSocketEntity
from custom_components.gardena_smart_system_ng.valve import GardenaValveEntity

from .conftest import ENTRY_DATA, make_mock_device


@pytest.fixture
async def coord(hass: HomeAssistant) -> GardenaCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, title="My Garden")
    entry.add_to_hass(hass)
    coordinator = GardenaCoordinator(hass, entry, async_get_clientsession(hass))
    coordinator._auth = AsyncMock()
    return coordinator


def test_valve_expected_check_and_optimistic(coord: GardenaCoordinator) -> None:
    device = make_mock_device(valve_count=1)
    service_id = next(iter(device.valves))
    entity = GardenaValveEntity(coord, device, service_id)

    assert entity._make_expected_state_check("NOPE") is None  # unknown command
    check = entity._make_expected_state_check("STOP_UNTIL_NEXT_TASK")
    assert check is not None

    coord.data = {}
    assert check() is False  # device missing
    no_valve = make_mock_device(valve_count=0)
    no_valve.valves = {}
    coord.data = {no_valve.device_id: no_valve}
    assert check() is False  # valve missing
    closed = make_mock_device(valve_count=1)  # activity == CLOSED matches STOP target
    coord.data = {closed.device_id: closed}
    assert check() is True

    coord.data = {}
    entity._apply_optimistic_state("STOP_UNTIL_NEXT_TASK", {})  # valve None → return
    coord.data = {device.device_id: device}
    entity._apply_optimistic_state("NOPE", {})  # unknown command → return


def test_switch_expected_check_and_optimistic(coord: GardenaCoordinator) -> None:
    device = make_mock_device(has_power_socket=True)
    entity = GardenaPowerSocketEntity(coord, device)

    assert entity._make_expected_state_check("NOPE") is None
    check = entity._make_expected_state_check("STOP_UNTIL_NEXT_TASK")
    assert check is not None

    coord.data = {}
    assert check() is False  # device missing
    no_ps = make_mock_device(has_power_socket=False)
    coord.data = {no_ps.device_id: no_ps}
    assert check() is False  # power_socket missing
    coord.data = {device.device_id: device}  # activity OFF matches STOP target
    assert check() is True

    coord.data = {}
    entity._apply_optimistic_state("STOP_UNTIL_NEXT_TASK", {})  # device None → return
    coord.data = {device.device_id: device}
    entity._apply_optimistic_state("NOPE", {})  # unknown command → return


def test_lawn_mower_expected_check(coord: GardenaCoordinator) -> None:
    device = make_mock_device(has_mower=True)
    entity = GardenaLawnMowerEntity(coord, device)

    assert entity._make_expected_state_check(None) is None
    check = entity._make_expected_state_check("parked")
    assert check is not None
    coord.data = {}
    assert check() is False  # device missing


def test_valve_event_handles_missing_valve(coord: GardenaCoordinator) -> None:
    device = make_mock_device(valve_count=1)
    service_id = next(iter(device.valves))
    entity = GardenaValveEventEntity(coord, device, service_id)
    entity.async_write_ha_state = MagicMock()  # avoid real HA state write

    no_valve = make_mock_device(valve_count=0)
    no_valve.valves = {}
    coord.data = {no_valve.device_id: no_valve}
    entity._handle_coordinator_update()  # valve gone → delegate to base and return
    entity.async_write_ha_state.assert_called()


async def test_wait_for_expected_state_confirms_after_push(
    coord: GardenaCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(entity_mod, "COMMAND_POLL_AFTER_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(entity_mod, "COMMAND_POLL_INTERVAL_SECONDS", 0.001)
    device = make_mock_device(valve_count=1)
    service_id = next(iter(device.valves))
    entity = GardenaValveEntity(coord, device, service_id)
    coord._ws_push_at[entity._device_id] = 100.0  # a push newer than marker 0.0

    calls: list[int] = []

    def check() -> bool:
        calls.append(1)
        return len(calls) > 1  # not confirmed on the first probe, confirmed after

    assert await entity._async_wait_for_expected_state(check, 0.0) is True


async def test_event_setup_skips_automower(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={**ENTRY_DATA, CONF_API_TYPE: "automower"}, title="Mower"
    )
    entry.add_to_hass(hass)
    added = MagicMock()
    await event_mod.async_setup_entry(hass, entry, added)  # early return for automower
    added.assert_not_called()
