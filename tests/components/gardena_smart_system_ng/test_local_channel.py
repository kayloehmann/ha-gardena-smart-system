"""Tests for the local gateway WebSocket channel's message handling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from gardena_smart_local_api.messages import (
    Entity,
    ErrorMessage,
    ErrorMetadata,
    Event,
    IngressMessageList,
    Reply,
)
from gardena_smart_local_api.resources import IpsoPath
from homeassistant.core import HomeAssistant

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

    import aiohttp

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

    await channel.async_start()
    for _ in range(20):  # pump the loop until discovery has built the device
        await asyncio.sleep(0.01)
        if dev in channel.devices:
            break
    await channel.async_stop()

    assert dev in channel.devices  # discovery built the device
    assert True in conn  # the link reported connected
    assert len(updates) >= 1  # discovery/event notified the coordinator
