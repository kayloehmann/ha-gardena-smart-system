"""Tests for the local gateway WebSocket channel's message handling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from gardena_smart_local_api.messages import (
    EgressMessageList,
    Entity,
    ErrorMessage,
    ErrorMetadata,
    Event,
    IngressMessageList,
    Reply,
    Request,
)
from gardena_smart_local_api.resources import IpsoPath
from homeassistant.core import HomeAssistant

from custom_components.gardena_smart_system_ng import local_channel as local_channel_mod
from custom_components.gardena_smart_system_ng.local_channel import (
    GardenaLocalChannel,
)


def _make_channel(hass: HomeAssistant) -> tuple[GardenaLocalChannel, list, list]:
    updates: list = []
    conn: list[bool] = []
    channel = GardenaLocalChannel(
        hass,
        host="10.0.0.9",
        password="deadbeef",
        on_devices_updated=updates.append,
        on_connection_change=conn.append,
    )
    return channel, updates, conn


async def test_reply_resolves_pending_future(hass: HomeAssistant) -> None:
    """A Reply with a matching request_id resolves the waiter's future."""
    channel, _, _ = _make_channel(hass)
    fut: asyncio.Future[Reply] = asyncio.get_running_loop().create_future()
    channel._pending["req-1"] = fut

    reply = Reply(request_id="req-1", success=True, payload={"vi": 0})
    channel._handle_ingress(IngressMessageList([reply]))

    assert fut.done()
    assert fut.result().success is True
    assert "req-1" not in channel._pending


async def test_error_message_fails_pending_future(hass: HomeAssistant) -> None:
    """An ErrorMessage for a pending request resolves it as unsuccessful."""
    channel, _, _ = _make_channel(hass)
    fut: asyncio.Future[Reply] = asyncio.get_running_loop().create_future()
    channel._pending["req-2"] = fut

    err = ErrorMessage(
        metadata=ErrorMetadata(error_source="websocketd"),
        payload={"vs": "nope"},
        request_id="req-2",
        success=False,
    )
    channel._handle_ingress(IngressMessageList([err]))

    assert fut.done()
    assert fut.result().success is False


async def test_unknown_device_event_is_ignored(hass: HomeAssistant) -> None:
    """An event for a device not in the map is dropped without notifying."""
    channel, updates, _ = _make_channel(hass)
    event = Event(
        entity=Entity(device="unknown", path=IpsoPath(object_name="lemonbeat")),
        op="update",
        payload={},
    )
    channel._handle_ingress(IngressMessageList([event]))

    assert updates == []  # nothing changed → no coordinator notification


async def test_send_command_false_when_disconnected(hass: HomeAssistant) -> None:
    """With no live socket, a command fails fast so the cloud path is used."""
    channel, _, _ = _make_channel(hass)
    assert channel._ws is None
    from gardena_smart_local_api.messages import EgressMessageList, Request

    request = EgressMessageList([Request(entity=Entity(path="x"), op="read")])
    assert await channel.async_send_command(request) is False


async def test_connection_change_fires_only_on_transition(hass: HomeAssistant) -> None:
    """The connection callback fires on edges, not on repeated same-state sets."""
    channel, _, conn = _make_channel(hass)
    channel._set_connected(True)
    channel._set_connected(True)  # no-op
    channel._set_connected(False)
    assert conn == [True, False]


async def test_send_command_resolves_on_matching_reply(hass: HomeAssistant) -> None:
    """A command send succeeds when the gateway acks its request_id."""
    from gardena_smart_local_api.messages import EgressMessageList, Request

    channel, _, _ = _make_channel(hass)
    fake_ws = MagicMock()
    fake_ws.closed = False
    fake_ws.send_str = AsyncMock()
    channel._ws = fake_ws

    request = EgressMessageList(
        [
            Request(
                entity=Entity(path="lemonbeat/0/watering_timer_1"), op="write", request_id="rid-1"
            )
        ]
    )
    task = asyncio.create_task(channel.async_send_command(request))
    await asyncio.sleep(0)  # let it send and register the pending future
    channel._handle_ingress(IngressMessageList([Reply(request_id="rid-1", success=True)]))

    assert await task is True
    fake_ws.send_str.assert_awaited_once()


async def test_event_updates_known_device(hass: HomeAssistant) -> None:
    """An update event for a known device applies and notifies the owner."""
    channel, updates, _ = _make_channel(hass)
    device = MagicMock()
    channel.devices = {"d": device}  # type: ignore[assignment]

    event = Event(
        entity=Entity(device="d", path=IpsoPath(object_name="lemonbeat")),
        op="update",
        payload={},
    )
    channel._handle_ingress(IngressMessageList([event]))

    device.update_data.assert_called_once()
    assert len(updates) == 1  # coordinator notified once


async def test_full_session_discovers_and_applies_events(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive a whole connection lifetime against a fake gateway WebSocket."""
    import json

    channel, updates, conn = _make_channel(hass)
    dev = "3034F8EE901EE94000001294"  # decodes to an Irrigation Control (model 31653)
    device_payload = {dev: {"device": {"0": {"model_number": {"vs": "31653"}}}}}

    def _text(obj: object) -> aiohttp.WSMessage:
        return aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, json.dumps(obj), "")

    class FakeWS:
        def __init__(self) -> None:
            self._q: asyncio.Queue[aiohttp.WSMessage] = asyncio.Queue()
            self.closed = False
            self._answered = False

        async def send_str(self, data: str) -> None:
            if self._answered:
                return
            self._answered = True
            for msg in json.loads(data):  # answer each discovery request_id
                rid = msg.get("request_id")
                await self._q.put(
                    _text([{"request_id": rid, "success": True, "payload": device_payload}])
                )
            # a live device update, then a server-initiated close
            await self._q.put(
                _text(
                    [
                        {
                            "entity": {"device": dev, "path": "lemonbeat/0"},
                            "op": "update",
                            "payload": {"_urn": "x", "rf_link_quality": {"vi": 100}},
                        }
                    ]
                )
            )
            await self._q.put(aiohttp.WSMessage(aiohttp.WSMsgType.CLOSED, None, ""))

        def __aiter__(self) -> "FakeWS":
            return self

        async def __anext__(self) -> aiohttp.WSMessage:
            return await self._q.get()

    class FakeCM:
        async def __aenter__(self) -> FakeWS:
            return FakeWS()

        async def __aexit__(self, *exc: object) -> bool:
            return False

    monkeypatch.setattr(channel._session, "ws_connect", lambda *a, **k: FakeCM())

    channel._ssl = MagicMock()
    await channel._session_once()

    assert dev in channel.devices  # discovery built the device
    assert True in conn  # the link reported connected
    assert len(updates) >= 1  # discovery/event notified the coordinator


async def test_connected_property_default_false(hass: HomeAssistant) -> None:
    channel, _, _ = _make_channel(hass)
    assert channel.connected is False


async def test_send_command_false_when_no_request_ids(hass: HomeAssistant) -> None:
    channel, _, _ = _make_channel(hass)
    ws = MagicMock()
    ws.closed = False
    channel._ws = ws
    request = EgressMessageList([Request(entity=Entity(path="x"), op="read", request_id=None)])
    assert await channel.async_send_command(request) is False


async def test_send_command_false_on_transport_error(hass: HomeAssistant) -> None:
    channel, _, _ = _make_channel(hass)
    ws = MagicMock()
    ws.closed = False
    ws.send_str = AsyncMock(side_effect=aiohttp.ClientError("boom"))
    channel._ws = ws
    request = EgressMessageList([Request(entity=Entity(path="x"), op="read", request_id="r")])
    assert await channel.async_send_command(request) is False


async def test_run_retries_after_session_error(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session error is swallowed and the loop reconnects until stopped."""
    channel, _, _ = _make_channel(hass)
    monkeypatch.setattr(local_channel_mod, "LOCAL_RECONNECT_SCHEDULE", (0.001,))
    calls: list[int] = []

    async def fake_session() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("boom")  # first attempt errors → reconnect
        await asyncio.sleep(3600)  # second attempt blocks until cancelled

    monkeypatch.setattr(channel, "_session_once", fake_session)
    await channel.async_start()
    for _ in range(50):
        await asyncio.sleep(0.005)
        if len(calls) >= 2:
            break
    await channel.async_stop()
    assert len(calls) >= 2


async def test_keepalive_returns_without_devices(hass: HomeAssistant) -> None:
    channel, _, _ = _make_channel(hass)
    channel.devices = {}  # type: ignore[assignment]
    await channel._keepalive(MagicMock())  # returns immediately, no send


async def test_keepalive_sends_until_closed(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    channel, _, _ = _make_channel(hass)
    monkeypatch.setattr(local_channel_mod, "KEEPALIVE_INTERVAL_SECONDS", 0.001)
    probe = MagicMock()
    probe.model_dump_json = MagicMock(return_value="[]")
    device = MagicMock()
    device.build_refresh_online_status_obj = probe
    channel.devices = {"d": device}  # type: ignore[assignment]

    ws = MagicMock()
    ws.send_str = AsyncMock()
    states = [False, True]  # one iteration, then closed
    type(ws).closed = property(lambda _self: states.pop(0) if states else True)

    await channel._keepalive(ws)
    ws.send_str.assert_awaited_once_with("[]")


async def test_non_conforming_frame_is_ignored(hass: HomeAssistant) -> None:
    channel, updates, _ = _make_channel(hass)
    channel._on_raw("not-json")  # invalid JSON
    channel._on_raw('{"not": "a list"}')  # valid JSON, wrong shape
    assert updates == []


async def test_error_frame_without_pending_is_logged(hass: HomeAssistant) -> None:
    channel, _, _ = _make_channel(hass)
    err = ErrorMessage(
        metadata=ErrorMetadata(error_source="websocketd"),
        payload={"vs": "boom"},
        request_id="unknown",
        success=False,
    )
    channel._handle_ingress(IngressMessageList([err]))  # no matching waiter → just logged


async def test_event_without_device_is_ignored(hass: HomeAssistant) -> None:
    channel, updates, _ = _make_channel(hass)
    event = Event(
        entity=Entity(device="", path=IpsoPath(object_name="lemonbeat")),
        op="update",
        payload={},
    )
    channel._handle_ingress(IngressMessageList([event]))
    assert updates == []


async def test_delete_event_removes_device(hass: HomeAssistant) -> None:
    channel, updates, _ = _make_channel(hass)
    channel.devices = {"d": MagicMock()}  # type: ignore[assignment]
    event = Event(entity=Entity(device="d", path=IpsoPath()), op="delete", payload={})
    channel._handle_ingress(IngressMessageList([event]))
    assert "d" not in channel.devices
    assert len(updates) == 1


async def test_fail_pending_cancels_open_futures(hass: HomeAssistant) -> None:
    channel, _, _ = _make_channel(hass)
    fut: asyncio.Future[Reply] = asyncio.get_running_loop().create_future()
    channel._pending["r"] = fut
    channel._fail_pending()
    assert fut.cancelled()
    assert channel._pending == {}
