"""Targeted coverage for base_coordinator edge paths (rate-limit, WS, MQTT)."""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,  # type: ignore[no-redef]
    )

from aiogardenasmart import GardenaConnectionError
from custom_components.gardena_smart_system_ng.base_coordinator import (
    BaseSmartSystemCoordinator,
    RateLimitState,
    _parse_iso_utc,
)
from custom_components.gardena_smart_system_ng.const import (
    DOMAIN,
    OPT_MQTT_ENABLE,
    WS_WATCHDOG_TIMEOUT_SECONDS,
)
from custom_components.gardena_smart_system_ng.coordinator import GardenaCoordinator

from .conftest import ENTRY_DATA, make_mock_device


@pytest.fixture
async def coord(hass: HomeAssistant) -> GardenaCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, title="My Garden")
    entry.add_to_hass(hass)
    c = GardenaCoordinator(hass, entry, async_get_clientsession(hass))
    c._auth = AsyncMock()
    return c


# ── RateLimitState / helpers ──────────────────────────────────────────


def test_parse_iso_utc_variants() -> None:
    assert _parse_iso_utc("") is None
    assert _parse_iso_utc("not-a-timestamp") is None  # malformed → None
    assert _parse_iso_utc("2020-01-01T00:00:00+00:00") is not None


def _state() -> RateLimitState:
    store = MagicMock()
    store.async_delay_save = MagicMock()
    store.async_save = AsyncMock()
    return RateLimitState(store)


def test_rate_limit_ladder_and_last_429() -> None:
    state = _state()
    assert state.last_429_at is None
    _state().reset_rate_limits()  # already clean → early return
    state.record_rate_limit()
    assert state.last_429_at is not None
    state.reset_rate_limits()
    assert state.rate_limit_hits == 0


def test_handshake_and_kill_switch() -> None:
    state = _state()
    state.clear_handshake_denials()  # already clean → early return
    state.record_handshake_denial()
    state.activate_kill_switch(timedelta(hours=1))
    assert state.is_kill_switch_active()
    state.activate_kill_switch(timedelta(seconds=-1))  # already expired
    assert state.kill_switch_remaining() is None
    state.clear_handshake_denials()
    assert state.ws_handshake_denials == 0


async def test_rate_limit_state_async_reset() -> None:
    store = MagicMock()
    store.async_delay_save = MagicMock()
    store.async_save = AsyncMock()
    state = RateLimitState(store)
    state.record_rate_limit()
    await state.async_reset()
    store.async_save.assert_awaited_once()
    assert state.rate_limit_hits == 0


# ── WebSocket start / device update ───────────────────────────────────


async def test_start_websocket_skips_when_already_connected(
    coord: GardenaCoordinator,
) -> None:
    coord._ws_connected = True
    await coord._async_start_websocket({})  # double-checks under lock and returns


async def test_ws_url_connection_error_records_failure(
    coord: GardenaCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    coord._ws_connected = False

    async def raise_conn(_devices: object) -> str:
        raise GardenaConnectionError("down")

    monkeypatch.setattr(coord, "_async_get_ws_url", raise_conn)
    recorder = MagicMock()
    monkeypatch.setattr(coord, "_record_ws_failure", recorder)
    await coord._async_start_websocket_locked({"d": make_mock_device()})
    recorder.assert_called_once()


async def test_on_device_update_publishes_to_mqtt(
    coord: GardenaCoordinator, hass: HomeAssistant
) -> None:
    bridge = MagicMock()
    bridge.is_active = True
    bridge.async_publish_device_state = AsyncMock()
    coord._mqtt_bridge = bridge
    coord.data = {}
    device = make_mock_device()
    coord._on_device_update(device.device_id, device)
    await hass.async_block_till_done()
    bridge.async_publish_device_state.assert_called_once()


async def test_update_data_publishes_all_when_bridge_active(
    coord: GardenaCoordinator, hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    devices = {d.device_id: d for d in [make_mock_device()]}

    async def fetch() -> dict:
        return devices

    monkeypatch.setattr(coord, "_async_fetch_devices", fetch)
    coord._ws_connected = True  # skip WS (re)start
    bridge = MagicMock()
    bridge.is_active = True
    bridge.async_publish_all_devices = AsyncMock()
    coord._mqtt_bridge = bridge

    await coord._async_update_data()
    await hass.async_block_till_done()
    bridge.async_publish_all_devices.assert_called_once()


# ── Reconnect loop / watchdog / session timer ─────────────────────────


async def test_reconnect_loop_stops_when_connected(
    coord: GardenaCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(coord, "_WS_RECONNECT_DELAYS", (0.001,))
    coord._ws_connected = True
    await coord._async_ws_reconnect_loop()


async def test_reconnect_loop_aborts_on_kill_switch(
    coord: GardenaCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(coord, "_WS_RECONNECT_DELAYS", (0.001,))
    coord._ws_connected = False
    coord._ws_cooldown_until = 0.0
    coord._rate_limit_state.activate_kill_switch(timedelta(hours=1))
    await coord._async_ws_reconnect_loop()


async def test_watchdog_returns_without_messages(coord: GardenaCoordinator) -> None:
    coord._ws_connected = True
    ws = MagicMock()
    ws.last_message_time = 0
    coord._ws = ws
    await coord._async_ws_watchdog_check()


async def test_watchdog_reconnects_on_silence(
    coord: GardenaCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    coord._ws_connected = True
    ws = MagicMock()
    ws.last_message_time = time.monotonic() - (WS_WATCHDOG_TIMEOUT_SECONDS + 5)
    ws.async_disconnect = AsyncMock(side_effect=aiohttp.ClientError("gone"))
    coord._ws = ws
    scheduler = MagicMock()
    monkeypatch.setattr(coord, "_schedule_ws_reconnect", scheduler)
    await coord._async_ws_watchdog_check()
    scheduler.assert_called_once()
    assert coord._ws is None


async def test_session_expired_noop_when_disconnected(
    coord: GardenaCoordinator,
) -> None:
    coord._ws_connected = False
    await coord._async_ws_session_expired()


async def test_session_expired_reconnects(
    coord: GardenaCoordinator, monkeypatch: pytest.MonkeyPatch
) -> None:
    coord._ws_connected = True
    ws = MagicMock()
    ws.async_disconnect = AsyncMock(side_effect=aiohttp.ClientError("gone"))
    coord._ws = ws
    scheduler = MagicMock()
    monkeypatch.setattr(coord, "_schedule_ws_reconnect", scheduler)
    await coord._async_ws_session_expired()
    scheduler.assert_called_once()
    assert coord._ws is None


# ── MQTT bridge lifecycle ─────────────────────────────────────────────


async def test_start_mqtt_bridge_creates_bridge(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, options={OPT_MQTT_ENABLE: True}, title="My Garden"
    )
    entry.add_to_hass(hass)
    coord = GardenaCoordinator(hass, entry, async_get_clientsession(hass))
    fake_bridge = MagicMock()
    fake_bridge.async_start = AsyncMock(return_value=True)
    with patch(
        "custom_components.gardena_smart_system_ng.mqtt_bridge.MqttBridge",
        return_value=fake_bridge,
    ):
        await coord._async_start_mqtt_bridge()
    assert coord._mqtt_bridge is fake_bridge


async def test_base_mqtt_command_handler_logs(coord: GardenaCoordinator) -> None:
    # The base handler is a no-op logger (GardenaCoordinator overrides it).
    await BaseSmartSystemCoordinator._async_handle_mqtt_command(coord, "d", {"action": "x"})


async def test_shutdown_stops_mqtt_bridge(coord: GardenaCoordinator) -> None:
    bridge = MagicMock()
    bridge.async_stop = AsyncMock()
    coord._mqtt_bridge = bridge
    await coord.async_shutdown()
    bridge.async_stop.assert_awaited_once()
