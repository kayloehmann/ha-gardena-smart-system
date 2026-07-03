"""Coverage for MqttBridge publish error paths and the command subscription."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.gardena_smart_system_ng.mqtt_bridge import MqttBridge

from .conftest import make_mock_device

_MQTT = "custom_components.gardena_smart_system_ng.mqtt_bridge.mqtt"


async def test_publish_device_state_swallows_broker_error(hass: HomeAssistant) -> None:
    bridge = MqttBridge(hass, "gardena", publish_states=True)
    bridge._started = True
    with patch(f"{_MQTT}.async_publish", AsyncMock(side_effect=HomeAssistantError("down"))):
        await bridge.async_publish_device_state("d", make_mock_device(valve_count=1))


async def test_publish_availability_paths(hass: HomeAssistant) -> None:
    bridge = MqttBridge(hass, "gardena", publish_states=True)
    bridge._started = False
    await bridge.async_publish_availability("d", True)  # not started → early return
    bridge._started = True
    with patch(f"{_MQTT}.async_publish", AsyncMock(side_effect=HomeAssistantError("down"))):
        await bridge.async_publish_availability("d", False)  # broker error swallowed


async def test_subscribe_and_command_dispatch(hass: HomeAssistant) -> None:
    handler = AsyncMock()
    bridge = MqttBridge(hass, "gardena", subscribe_commands=True)
    bridge._command_handler = handler

    captured: dict[str, object] = {}

    async def fake_subscribe(_hass: object, _topic: str, cb: object) -> MagicMock:
        captured["cb"] = cb
        return MagicMock()

    with patch(f"{_MQTT}.async_subscribe", fake_subscribe):
        await bridge._async_subscribe()

    on_command = captured["cb"]
    on_command(MagicMock(topic="gardena/short", payload="{}"))  # too few parts → ignored
    on_command(MagicMock(topic="gardena/dev/command", payload="not-json"))  # bad JSON → warned
    on_command(MagicMock(topic="gardena/dev/command", payload='{"action": "x"}'))  # dispatched
    await hass.async_block_till_done()
    handler.assert_called_once()
