"""Coverage for Automower entity device-missing guards and the confirmation wait."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,  # type: ignore[no-redef]
    )

from custom_components.gardena_smart_system_ng import automower_entity as automower_entity_mod
from custom_components.gardena_smart_system_ng.automower_button import (
    AutomowerConfirmErrorButton,
)
from custom_components.gardena_smart_system_ng.automower_coordinator import (
    AutomowerCoordinator,
)
from custom_components.gardena_smart_system_ng.automower_lawn_mower import (
    AutomowerLawnMowerEntity,
)
from custom_components.gardena_smart_system_ng.automower_number import (
    AutomowerScheduleOverrideEntity,
)
from custom_components.gardena_smart_system_ng.automower_select import (
    AutomowerHeadlightSelect,
)
from custom_components.gardena_smart_system_ng.automower_select import (
    async_setup_entry as select_setup,
)
from custom_components.gardena_smart_system_ng.automower_switch import (
    AutomowerWorkAreaSwitch,
)
from custom_components.gardena_smart_system_ng.const import (
    API_TYPE_AUTOMOWER,
    CONF_API_TYPE,
    DOMAIN,
)

from .conftest import ENTRY_DATA
from .test_automower import make_mock_automower_device


@pytest.fixture
async def coord(hass: HomeAssistant) -> AutomowerCoordinator:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY_DATA, CONF_API_TYPE: API_TYPE_AUTOMOWER},
        title="Mower",
    )
    entry.add_to_hass(hass)
    coordinator = AutomowerCoordinator(hass, entry, async_get_clientsession(hass))
    coordinator._auth = AsyncMock()
    return coordinator


async def test_button_press_without_device_raises(coord: AutomowerCoordinator) -> None:
    device = make_mock_automower_device(is_error_confirmable=True, can_confirm_error=True)
    entity = AutomowerConfirmErrorButton(coord, device)
    coord.data = {}
    with pytest.raises(HomeAssistantError):
        await entity.async_press()


async def test_number_override_none_and_raise(coord: AutomowerCoordinator) -> None:
    device = make_mock_automower_device()
    entity = AutomowerScheduleOverrideEntity(coord, device)
    coord.data = {}
    assert entity.native_value is None
    with pytest.raises(HomeAssistantError):
        await entity.async_set_native_value(30)


async def test_select_none_and_raise(coord: AutomowerCoordinator) -> None:
    device = make_mock_automower_device()
    entity = AutomowerHeadlightSelect(coord, device)
    coord.data = {}
    assert entity.current_option is None
    with pytest.raises(HomeAssistantError):
        await entity.async_select_option("always_on")


async def test_select_setup_skips_non_automower(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, title="Garden")  # no automower type
    entry.add_to_hass(hass)
    added = MagicMock()
    await select_setup(hass, entry, added)
    added.assert_not_called()


async def test_work_area_switch_none_and_raise(coord: AutomowerCoordinator) -> None:
    device = make_mock_automower_device(has_work_areas=True)
    work_area_id = next(iter(device.work_areas), 0)
    entity = AutomowerWorkAreaSwitch(coord, device, work_area_id)
    coord.data = {}
    assert entity.is_on is None
    with pytest.raises(HomeAssistantError):
        await entity.async_turn_on()


async def test_lawn_mower_check_without_device(coord: AutomowerCoordinator) -> None:
    device = make_mock_automower_device()
    entity = AutomowerLawnMowerEntity(coord, device)
    check = entity._make_expected_state_check("mowing")
    assert check is not None
    coord.data = {}
    assert check() is False


async def test_wait_for_expected_state_confirms(
    coord: AutomowerCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(automower_entity_mod, "COMMAND_POLL_AFTER_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(automower_entity_mod, "COMMAND_POLL_INTERVAL_SECONDS", 0.001)
    device = make_mock_automower_device()
    entity = AutomowerLawnMowerEntity(coord, device)
    coord._ws_push_at[entity._mower_id] = 100.0

    calls: list[int] = []

    def check() -> bool:
        calls.append(1)
        return len(calls) > 1

    assert await entity._async_wait_for_expected_state(check, 0.0) is True
