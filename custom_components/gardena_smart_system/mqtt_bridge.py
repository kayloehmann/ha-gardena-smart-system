"""MQTT state bridge for the Gardena Smart System integration.

Publishes device states to a local MQTT broker and optionally accepts
commands via MQTT topics. Requires the HA MQTT integration to be configured.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import DEFAULT_MQTT_TOPIC_PREFIX

_LOGGER = logging.getLogger(__name__)


def _is_mqtt_available(hass: HomeAssistant) -> bool:
    """Check if the MQTT integration is loaded and available."""
    return "mqtt" in hass.config.components


def _serialize_device(device: Any) -> dict[str, Any]:
    """Serialize a Gardena device to a JSON-safe dictionary."""
    data: dict[str, Any] = {
        "device_id": getattr(device, "device_id", None),
        "name": getattr(device, "name", None),
        "is_online": getattr(device, "is_online", None),
    }

    common = getattr(device, "common", None)
    if common is not None:
        data["common"] = {
            "battery_level": getattr(common, "battery_level", None),
            "battery_state": getattr(common, "battery_state", None),
            "rf_link_level": getattr(common, "rf_link_level", None),
            "rf_link_state": getattr(common, "rf_link_state", None),
        }

    sensor = getattr(device, "sensor", None)
    if sensor is not None:
        data["sensor"] = {
            "soil_humidity": getattr(sensor, "soil_humidity", None),
            "soil_temperature": getattr(sensor, "soil_temperature", None),
            "ambient_temperature": getattr(sensor, "ambient_temperature", None),
            "light_intensity": getattr(sensor, "light_intensity", None),
        }

    valves = getattr(device, "valves", None)
    if valves:
        data["valves"] = {}
        for vid, valve in valves.items():
            data["valves"][vid] = {
                "activity": getattr(valve, "activity", None),
                "state": getattr(valve, "state", None),
                "duration": getattr(valve, "duration", None),
                "name": getattr(valve, "name", None),
            }

    mower = getattr(device, "mower", None)
    if mower is not None:
        data["mower"] = {
            "activity": getattr(mower, "activity", None),
            "state": getattr(mower, "state", None),
            "operating_hours": getattr(mower, "operating_hours", None),
            "last_error_code": getattr(mower, "last_error_code", None),
        }

    ps = getattr(device, "power_socket", None)
    if ps is not None:
        data["power_socket"] = {
            "activity": getattr(ps, "activity", None),
            "state": getattr(ps, "state", None),
            "duration": getattr(ps, "duration", None),
        }

    return data


class MqttBridge:
    """Publishes Gardena device state to MQTT and handles inbound commands."""

    def __init__(
        self,
        hass: HomeAssistant,
        topic_prefix: str = DEFAULT_MQTT_TOPIC_PREFIX,
        *,
        publish_states: bool = True,
        subscribe_commands: bool = True,
    ) -> None:
        """Initialize the MQTT bridge."""
        self._hass = hass
        self._topic_prefix = topic_prefix.rstrip("/")
        self._publish_states = publish_states
        self._subscribe_commands = subscribe_commands
        self._unsub_command: Any = None
        self._command_handler: Any = None
        self._started = False

    @property
    def is_active(self) -> bool:
        """Whether the bridge is currently running."""
        return self._started

    async def async_start(self, command_handler: Any = None) -> bool:
        """Start the MQTT bridge. Returns True if started successfully."""
        if not _is_mqtt_available(self._hass):
            _LOGGER.debug("MQTT integration not available, bridge not started")
            return False

        self._command_handler = command_handler
        self._started = True

        if self._subscribe_commands and command_handler is not None:
            await self._async_subscribe()

        _LOGGER.info(
            "MQTT bridge started (prefix=%s, publish=%s, commands=%s)",
            self._topic_prefix,
            self._publish_states,
            self._subscribe_commands,
        )
        return True

    async def async_stop(self) -> None:
        """Stop the MQTT bridge and unsubscribe from topics."""
        if self._unsub_command is not None:
            self._unsub_command()
            self._unsub_command = None
        self._started = False
        _LOGGER.debug("MQTT bridge stopped")

    async def async_publish_device_state(self, device_id: str, device: Any) -> None:
        """Publish a device's full state to MQTT."""
        if not self._started or not self._publish_states:
            return

        topic = f"{self._topic_prefix}/{device_id}/state"
        payload = json.dumps(_serialize_device(device), default=str)

        try:
            await mqtt.async_publish(self._hass, topic, payload, qos=1, retain=True)
        except HomeAssistantError:
            # MQTT broker dropped the publish (offline, unauthorised, topic
            # refused). Failing a single state update is fine — the next one
            # refreshes the retained topic.
            _LOGGER.debug("Failed to publish MQTT state for %s", device_id)

    async def async_publish_availability(self, device_id: str, available: bool) -> None:
        """Publish device availability to MQTT."""
        if not self._started or not self._publish_states:
            return

        topic = f"{self._topic_prefix}/{device_id}/availability"
        payload = "online" if available else "offline"

        try:
            await mqtt.async_publish(self._hass, topic, payload, qos=1, retain=True)
        except HomeAssistantError:
            _LOGGER.debug("Failed to publish MQTT availability for %s", device_id)

    async def async_publish_all_devices(self, devices: dict[str, Any]) -> None:
        """Publish state for all known devices."""
        for device_id, device in devices.items():
            await self.async_publish_device_state(device_id, device)
            is_online = getattr(device, "is_online", True)
            await self.async_publish_availability(device_id, is_online)

    async def _async_subscribe(self) -> None:
        """Subscribe to command topics."""
        topic = f"{self._topic_prefix}/+/command"

        @callback
        def _on_command(message: Any) -> None:
            """Handle an inbound MQTT command."""
            parts = message.topic.split("/")
            if len(parts) < 3:
                return
            device_id = parts[-2]

            try:
                payload = json.loads(message.payload)
            except (json.JSONDecodeError, TypeError):
                _LOGGER.warning("Invalid MQTT command payload on %s", message.topic)
                return

            _LOGGER.debug("MQTT command for %s: %s", device_id, payload)
            if self._command_handler is not None:
                self._hass.async_create_task(self._command_handler(device_id, payload))

        self._unsub_command = await mqtt.async_subscribe(self._hass, topic, _on_command)
        _LOGGER.debug("Subscribed to MQTT commands on %s", topic)
