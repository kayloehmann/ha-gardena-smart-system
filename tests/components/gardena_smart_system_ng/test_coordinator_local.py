"""Tests for the local-gateway wiring in GardenaCoordinator."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,  # type: ignore[no-redef]
    )

from custom_components.gardena_smart_system_ng.binary_sensor import HubLocalConnectionSensor
from custom_components.gardena_smart_system_ng.const import (
    DOMAIN,
    OPT_LOCAL_ENABLE,
    OPT_LOCAL_HOST,
)
from custom_components.gardena_smart_system_ng.coordinator import GardenaCoordinator
from custom_components.gardena_smart_system_ng.sensor import (
    GardenaCommandSourceSensor,
    _hub_device_info,
)

from .conftest import ENTRY_DATA, make_mock_device

# A real SGTIN96 id that decodes to serial 00004756 (see local_ids tests).
LOCAL_ID = "3034F8EE901EE94000001294"
CLOUD_SERIAL = "00004756"

_PATCH_LOCAL_CHANNEL = "custom_components.gardena_smart_system_ng.coordinator.GardenaLocalChannel"


class FakeLocalDevice:
    def __init__(self) -> None:
        self.id = LOCAL_ID
        self.valve_ids = [0]

    def build_open_valve_obj(self, valve_id: int, seconds: int) -> str:
        return f"open:{valve_id}:{seconds}"

    def build_close_valve_obj(self, valve_id: int) -> str:
        return f"close:{valve_id}"


class FakeChannel:
    def __init__(self, *, connected: bool = True, ack: bool = True) -> None:
        self.connected = connected
        self.devices = {LOCAL_ID: FakeLocalDevice()}
        self._ack = ack
        self.sent: list[Any] = []
        self.stopped = False

    async def async_send_command(self, request: Any) -> bool:
        self.sent.append(request)
        return self._ack

    async def async_stop(self) -> None:
        self.stopped = True


def _cloud_device() -> MagicMock:
    device = MagicMock()
    device.device_id = "dev-uuid"
    device.serial = CLOUD_SERIAL
    device.valves = {"dev-uuid:1": MagicMock()}
    return device


@pytest.fixture
async def coordinator(hass: HomeAssistant) -> GardenaCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, title="My Garden")
    entry.add_to_hass(hass)
    coord = GardenaCoordinator(hass, entry, async_get_clientsession(hass))
    coord.data = {"dev-uuid": _cloud_device()}
    coord._client = AsyncMock()
    return coord


async def test_command_goes_local_when_connected(coordinator: GardenaCoordinator) -> None:
    channel = FakeChannel(connected=True, ack=True)
    coordinator._local_channel = channel  # type: ignore[assignment]

    await coordinator.async_send_command(
        "dev-uuid:1", "VALVE_CONTROL", "START_SECONDS_TO_OVERRIDE", seconds=600
    )

    assert channel.sent == ["open:0:600"]
    coordinator._client.async_send_command.assert_not_called()
    assert coordinator.last_command_source("dev-uuid") == "local"


async def test_command_falls_back_to_cloud_without_channel(
    coordinator: GardenaCoordinator,
) -> None:
    await coordinator.async_send_command("dev-uuid:1", "VALVE_CONTROL", "STOP_UNTIL_NEXT_TASK")

    coordinator._client.async_send_command.assert_called_once_with(
        service_id="dev-uuid:1", control_type="VALVE_CONTROL", command="STOP_UNTIL_NEXT_TASK"
    )
    assert coordinator.last_command_source("dev-uuid") == "cloud"


async def test_command_falls_back_when_local_not_acked(
    coordinator: GardenaCoordinator,
) -> None:
    coordinator._local_channel = FakeChannel(connected=True, ack=False)  # type: ignore[assignment]

    await coordinator.async_send_command("dev-uuid:1", "VALVE_CONTROL", "STOP_UNTIL_NEXT_TASK")

    coordinator._client.async_send_command.assert_called_once()
    assert coordinator.last_command_source("dev-uuid") == "cloud"


async def test_local_command_does_not_touch_budget_or_throttle(
    coordinator: GardenaCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator._local_channel = FakeChannel(connected=True, ack=True)  # type: ignore[assignment]
    throttle = MagicMock()
    increment = MagicMock()
    monkeypatch.setattr(coordinator, "check_command_throttle", throttle)
    monkeypatch.setattr(coordinator._api_budget, "increment", increment)

    await coordinator.async_send_command(
        "dev-uuid:1", "VALVE_CONTROL", "START_SECONDS_TO_OVERRIDE", seconds=600
    )

    throttle.assert_not_called()  # local command is not rate-limited
    increment.assert_not_called()  # and consumes no cloud quota
    assert coordinator.last_command_source("dev-uuid") == "local"


async def test_cloud_command_throttles_and_counts_budget(
    coordinator: GardenaCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    throttle = MagicMock()
    increment = MagicMock()
    monkeypatch.setattr(coordinator, "check_command_throttle", throttle)
    monkeypatch.setattr(coordinator._api_budget, "increment", increment)

    await coordinator.async_send_command(  # no local channel → cloud path
        "dev-uuid:1", "VALVE_CONTROL", "STOP_UNTIL_NEXT_TASK"
    )

    throttle.assert_called_once()
    increment.assert_called_once()
    coordinator._client.async_send_command.assert_called_once()
    assert coordinator.last_command_source("dev-uuid") == "cloud"


async def test_local_command_works_when_cloud_budget_exhausted(
    coordinator: GardenaCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator._local_channel = FakeChannel(connected=True, ack=True)  # type: ignore[assignment]
    # If the cloud path were taken this would raise; the local path must not.
    monkeypatch.setattr(
        coordinator,
        "check_command_throttle",
        MagicMock(side_effect=HomeAssistantError("exhausted")),
    )

    await coordinator.async_send_command("dev-uuid:1", "VALVE_CONTROL", "STOP_UNTIL_NEXT_TASK")

    assert coordinator.last_command_source("dev-uuid") == "local"
    coordinator._client.async_send_command.assert_not_called()


async def test_local_overlay_pushes_update_on_change(
    coordinator: GardenaCoordinator,
) -> None:
    listener = MagicMock()
    coordinator.async_add_listener(listener)
    with patch(
        "custom_components.gardena_smart_system_ng.coordinator.apply_local_state",
        return_value=True,
    ):
        coordinator._on_local_devices_updated({LOCAL_ID: FakeLocalDevice()})
    listener.assert_called()


async def test_command_cloud_when_local_device_unknown(
    coordinator: GardenaCoordinator,
) -> None:
    channel = FakeChannel(connected=True)
    channel.devices = {}  # no local device matches the cloud serial
    coordinator._local_channel = channel  # type: ignore[assignment]

    await coordinator.async_send_command("dev-uuid:1", "VALVE_CONTROL", "STOP_UNTIL_NEXT_TASK")

    coordinator._client.async_send_command.assert_called_once()
    assert coordinator.last_command_source("dev-uuid") == "cloud"


async def test_on_device_update_reasserts_local(coordinator: GardenaCoordinator) -> None:
    coordinator._local_channel = FakeChannel(connected=True)  # type: ignore[assignment]
    listener = MagicMock()
    coordinator.async_add_listener(listener)
    device = coordinator.data["dev-uuid"]
    with patch(
        "custom_components.gardena_smart_system_ng.coordinator.apply_local_state",
        return_value=True,
    ):
        coordinator._on_device_update("dev-uuid", device)
    listener.assert_called()


async def test_shutdown_stops_local_channel(coordinator: GardenaCoordinator) -> None:
    channel = FakeChannel(connected=True)
    coordinator._local_channel = channel  # type: ignore[assignment]
    coordinator._auth = AsyncMock()  # avoid real token revocation on shutdown

    await coordinator.async_shutdown()

    assert channel.stopped is True
    assert coordinator._local_channel is None


async def test_command_cloud_when_local_command_unmappable(
    coordinator: GardenaCoordinator,
) -> None:
    coordinator._local_channel = FakeChannel(connected=True)  # type: ignore[assignment]
    # Local device matches, but START_DONT_OVERRIDE has no local equivalent.
    await coordinator.async_send_command("dev-uuid:1", "VALVE_CONTROL", "START_DONT_OVERRIDE")
    coordinator._client.async_send_command.assert_called_once()
    assert coordinator.last_command_source("dev-uuid") == "cloud"


async def test_command_cloud_when_device_not_in_data(
    coordinator: GardenaCoordinator,
) -> None:
    coordinator._local_channel = FakeChannel(connected=True)  # type: ignore[assignment]
    await coordinator.async_send_command("other-uuid:1", "VALVE_CONTROL", "STOP_UNTIL_NEXT_TASK")
    coordinator._client.async_send_command.assert_called_once()
    assert coordinator.last_command_source("other-uuid") == "cloud"


def test_client_property_returns_rest_client(coordinator: GardenaCoordinator) -> None:
    assert coordinator.client is coordinator._client


async def test_overlay_noop_without_data(coordinator: GardenaCoordinator) -> None:
    coordinator.data = None
    coordinator._on_local_devices_updated({LOCAL_ID: FakeLocalDevice()})  # no error, no push


async def test_set_local_connected_notifies_listeners(
    coordinator: GardenaCoordinator,
) -> None:
    listener = MagicMock()
    coordinator.async_add_listener(listener)
    coordinator._set_local_connected(True)
    assert coordinator.local_connected is True
    listener.assert_called()


def test_local_connection_binary_sensor(coordinator: GardenaCoordinator) -> None:
    sensor = HubLocalConnectionSensor(coordinator, coordinator.config_entry, _hub_device_info)
    assert sensor.is_on is False
    coordinator._local_connected = True
    assert sensor.is_on is True


def test_command_source_sensor(coordinator: GardenaCoordinator) -> None:
    device = coordinator.data["dev-uuid"]
    sensor = GardenaCommandSourceSensor(coordinator, device)
    assert sensor.native_value is None
    coordinator._last_command_source["dev-uuid"] = "local"
    assert sensor.native_value == "local"


async def test_ensure_channel_starts_and_stops_with_options(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={OPT_LOCAL_ENABLE: True, OPT_LOCAL_HOST: "10.0.0.9"},
        title="My Garden",
    )
    entry.add_to_hass(hass)
    coord = GardenaCoordinator(hass, entry, async_get_clientsession(hass))

    fake = MagicMock()
    fake.async_start = AsyncMock()
    fake.async_stop = AsyncMock()
    with patch(_PATCH_LOCAL_CHANNEL, return_value=fake) as ctor:
        await coord._async_ensure_local_channel()
        ctor.assert_called_once()
        fake.async_start.assert_awaited_once()

        # Disable via options → channel is stopped and cleared.
        hass.config_entries.async_update_entry(entry, options={OPT_LOCAL_ENABLE: False})
        await coord._async_ensure_local_channel()
        fake.async_stop.assert_awaited_once()
        assert coord._local_channel is None


async def test_local_entities_created_on_setup(hass: HomeAssistant) -> None:
    """With local access enabled, the local-status and command-source entities exist."""
    device = make_mock_device(valve_count=1, has_sensor=False)  # a controllable device
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={OPT_LOCAL_ENABLE: True, OPT_LOCAL_HOST: "10.0.0.9"},
        title="My Garden",
    )
    fake_channel = MagicMock()
    fake_channel.async_start = AsyncMock()
    fake_channel.async_stop = AsyncMock()
    fake_channel.connected = False
    fake_channel.devices = {}

    p_client = "custom_components.gardena_smart_system_ng.coordinator.GardenaClient"
    p_auth = "custom_components.gardena_smart_system_ng.coordinator.GardenaAuth"
    p_ws = "custom_components.gardena_smart_system_ng.coordinator.GardenaWebSocket"
    with (
        patch(p_client) as client_cls,
        patch(p_auth, return_value=AsyncMock()),
        patch(p_ws) as ws_cls,
        patch(_PATCH_LOCAL_CHANNEL, return_value=fake_channel),
    ):
        client = AsyncMock()
        client.async_get_devices = AsyncMock(return_value={device.device_id: device})
        client.async_get_websocket_url = AsyncMock(return_value="wss://test")
        client_cls.return_value = client
        ws = AsyncMock()
        ws.async_connect = AsyncMock()
        ws.async_disconnect = AsyncMock()
        ws_cls.return_value = ws

        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    unique_ids = {e.unique_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert any(u.endswith("_command_source") for u in unique_ids)
    assert f"hub_{entry.entry_id}_local_connected" in unique_ids
