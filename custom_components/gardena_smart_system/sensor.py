"""Sensor platform for the Gardena Smart System integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from aiogardenasmart import Device

from . import GardenaConfigEntry
from .base_coordinator import BaseSmartSystemCoordinator
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE, DOMAIN
from .coordinator import GardenaCoordinator
from .entity import GardenaEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GardenaSensorDescription(SensorEntityDescription):
    """Sensor description with a typed value extractor."""

    value_fn: Callable[[Device], Any]
    exists_fn: Callable[[Device], bool] = lambda _: True


COMMON_SENSORS: tuple[GardenaSensorDescription, ...] = (
    GardenaSensorDescription(
        key="battery_level",
        translation_key="battery_level",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        value_fn=lambda d: d.common.battery_level if d.common else None,
        exists_fn=lambda d: d.common is not None and d.common.battery_level is not None,
    ),
    GardenaSensorDescription(
        key="battery_state",
        translation_key="battery_state",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=[
            "ok",
            "low",
            "replace_now",
            "out_of_operation",
            "charging",
            "no_battery",
            "unknown",
        ],
        value_fn=lambda d: (
            d.common.battery_state.lower() if d.common and d.common.battery_state else None
        ),
        exists_fn=lambda d: d.common is not None and d.common.battery_state is not None,
    ),
    GardenaSensorDescription(
        key="rf_link_level",
        translation_key="rf_link_level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=0,
        value_fn=lambda d: d.common.rf_link_level if d.common else None,
        exists_fn=lambda d: d.common is not None and d.common.rf_link_level is not None,
    ),
)

SENSOR_SENSORS: tuple[GardenaSensorDescription, ...] = (
    GardenaSensorDescription(
        key="soil_humidity",
        translation_key="soil_humidity",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.MOISTURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: d.sensor.soil_humidity if d.sensor else None,
        exists_fn=lambda d: d.sensor is not None and d.sensor.soil_humidity is not None,
    ),
    GardenaSensorDescription(
        key="soil_temperature",
        translation_key="soil_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.sensor.soil_temperature if d.sensor else None,
        exists_fn=lambda d: d.sensor is not None and d.sensor.soil_temperature is not None,
    ),
    GardenaSensorDescription(
        key="ambient_temperature",
        translation_key="ambient_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: d.sensor.ambient_temperature if d.sensor else None,
        exists_fn=lambda d: d.sensor is not None and d.sensor.ambient_temperature is not None,
    ),
    GardenaSensorDescription(
        key="light_intensity",
        translation_key="light_intensity",
        native_unit_of_measurement="lx",
        device_class=SensorDeviceClass.ILLUMINANCE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.sensor.light_intensity if d.sensor else None,
        exists_fn=lambda d: d.sensor is not None and d.sensor.light_intensity is not None,
    ),
)

POWER_SOCKET_SENSORS: tuple[GardenaSensorDescription, ...] = (
    GardenaSensorDescription(
        key="power_socket_remaining_duration",
        translation_key="power_socket_remaining_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: (
            d.power_socket.duration
            if d.power_socket and d.power_socket.duration and d.power_socket.duration > 0
            else None
        ),
        exists_fn=lambda d: d.power_socket is not None,
    ),
    GardenaSensorDescription(
        key="power_socket_state",
        translation_key="power_socket_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            d.power_socket.state.lower() if d.power_socket and d.power_socket.state else None
        ),
        exists_fn=lambda d: d.power_socket is not None and d.power_socket.state is not None,
    ),
    GardenaSensorDescription(
        key="power_socket_last_error_code",
        translation_key="power_socket_last_error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.power_socket.last_error_code if d.power_socket else None,
        exists_fn=lambda d: d.power_socket is not None,
    ),
)

MOWER_SENSORS: tuple[GardenaSensorDescription, ...] = (
    GardenaSensorDescription(
        key="mower_operating_hours",
        translation_key="mower_operating_hours",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.mower.operating_hours if d.mower else None,
        exists_fn=lambda d: d.mower is not None,
    ),
    GardenaSensorDescription(
        key="mower_activity",
        translation_key="mower_activity",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.mower.activity if d.mower else None,
        exists_fn=lambda d: d.mower is not None,
    ),
    GardenaSensorDescription(
        key="mower_state",
        translation_key="mower_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.mower.state.lower() if d.mower and d.mower.state else None,
        exists_fn=lambda d: d.mower is not None and d.mower.state is not None,
    ),
    GardenaSensorDescription(
        key="mower_last_error_code",
        translation_key="mower_last_error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.mower.last_error_code if d.mower else None,
        exists_fn=lambda d: d.mower is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gardena sensor entities from a config entry."""
    if entry.data.get(CONF_API_TYPE) == API_TYPE_AUTOMOWER:
        from .automower_sensor import async_setup_entry as automower_setup

        await automower_setup(hass, entry, async_add_entities)
        # Hub-level diagnostic sensors for Automower too
        coordinator = entry.runtime_data
        async_add_entities(
            [
                HubDeviceCountSensor(coordinator, entry),
                HubPollingIntervalSensor(coordinator, entry),
            ]
        )
        return

    coordinator = cast(GardenaCoordinator, entry.runtime_data)
    known_keys: set[tuple[str, str]] = set()

    @callback
    def _async_add_new_entities() -> None:
        if coordinator.data is None:
            return  # type: ignore[unreachable]
        new_entities: list[SensorEntity] = []
        for device in coordinator.data.values():
            for description in (
                *COMMON_SENSORS,
                *SENSOR_SENSORS,
                *MOWER_SENSORS,
                *POWER_SOCKET_SENSORS,
            ):
                key = (device.device_id, description.key)
                if key not in known_keys and description.exists_fn(device):
                    known_keys.add(key)
                    new_entities.append(GardenaSensorEntity(coordinator, device, description))
            # Per-valve remaining duration sensors
            for service_id in device.valves:
                valve_suffix = service_id.split(":")[-1] if ":" in service_id else service_id
                dur_key = (
                    device.device_id,
                    f"valve_{valve_suffix}_remaining_duration",
                )
                if dur_key not in known_keys:
                    known_keys.add(dur_key)
                    new_entities.append(
                        GardenaValveRemainingDurationSensor(coordinator, device, service_id)
                    )
            # Per-valve error code sensors
            for service_id in device.valves:
                valve_suffix = service_id.split(":")[-1] if ":" in service_id else service_id
                key = (device.device_id, f"valve_{valve_suffix}_last_error_code")
                if key not in known_keys:
                    known_keys.add(key)
                    new_entities.append(GardenaValveErrorSensor(coordinator, device, service_id))
            # Per-valve state sensors
            for service_id in device.valves:
                valve_suffix = service_id.split(":")[-1] if ":" in service_id else service_id
                key = (device.device_id, f"valve_{valve_suffix}_state")
                if key not in known_keys:
                    known_keys.add(key)
                    new_entities.append(GardenaValveStateSensor(coordinator, device, service_id))
            # ValveSet error sensor
            if device.valve_set is not None:
                vs_key = (device.device_id, "valve_set_last_error_code")
                if vs_key not in known_keys:
                    known_keys.add(vs_key)
                    new_entities.append(GardenaValveSetErrorSensor(coordinator, device))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_entities))
    _async_add_new_entities()

    # Hub-level diagnostic sensors (coordinator state)
    async_add_entities(
        [
            HubDeviceCountSensor(coordinator, entry),
            HubPollingIntervalSensor(coordinator, entry),
        ]
    )


class GardenaSensorEntity(GardenaEntity, SensorEntity):
    """A sensor entity for Gardena Smart System devices."""

    entity_description: GardenaSensorDescription

    def __init__(
        self,
        coordinator: GardenaCoordinator,
        device: Device,
        description: GardenaSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        device = self._device
        if device is None:
            return None
        return self.entity_description.value_fn(device)


class GardenaValveRemainingDurationSensor(GardenaEntity, SensorEntity):
    """Remaining watering duration sensor for a specific Gardena valve."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_translation_key = "valve_remaining_duration"

    def __init__(
        self,
        coordinator: GardenaCoordinator,
        device: Device,
        service_id: str,
    ) -> None:
        """Initialize the valve remaining duration sensor."""
        zone = service_id.split(":")[-1] if ":" in service_id else ""
        suffix = f"valve_{zone}_remaining_duration" if zone else "valve_remaining_duration"
        super().__init__(coordinator, device, suffix)
        self._service_id = service_id
        if zone:
            self._attr_translation_placeholders = {"zone": zone}

    @property
    def native_value(self) -> int | None:
        """Return the valve's remaining duration in seconds."""
        device = self._device
        if device is None:
            return None
        valve = device.valves.get(self._service_id)
        if valve is None:
            return None
        if valve.duration is not None and valve.duration > 0:
            return valve.duration
        return None


class GardenaValveErrorSensor(GardenaEntity, SensorEntity):
    """Last error code sensor for a specific Gardena valve."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "valve_last_error_code"

    def __init__(
        self,
        coordinator: GardenaCoordinator,
        device: Device,
        service_id: str,
    ) -> None:
        """Initialize the valve error sensor."""
        zone = service_id.split(":")[-1] if ":" in service_id else ""
        suffix = f"valve_{zone}_last_error_code" if zone else "valve_last_error_code"
        super().__init__(coordinator, device, suffix)
        self._service_id = service_id
        if zone:
            self._attr_translation_placeholders = {"zone": zone}

    @property
    def native_value(self) -> str | None:
        """Return the valve's last error code."""
        device = self._device
        if device is None:
            return None
        valve = device.valves.get(self._service_id)
        if valve is None:
            return None
        return valve.last_error_code


class GardenaValveStateSensor(GardenaEntity, SensorEntity):
    """State sensor for a specific Gardena valve."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "valve_state"

    def __init__(
        self,
        coordinator: GardenaCoordinator,
        device: Device,
        service_id: str,
    ) -> None:
        """Initialize the valve state sensor."""
        zone = service_id.split(":")[-1] if ":" in service_id else ""
        suffix = f"valve_{zone}_state" if zone else "valve_state"
        super().__init__(coordinator, device, suffix)
        self._service_id = service_id
        if zone:
            self._attr_translation_placeholders = {"zone": zone}

    @property
    def native_value(self) -> str | None:
        """Return the valve's state."""
        device = self._device
        if device is None:
            return None
        valve = device.valves.get(self._service_id)
        if valve is None:
            return None
        return valve.state.lower() if valve.state else None


class GardenaValveSetErrorSensor(GardenaEntity, SensorEntity):
    """Last error code sensor for a Gardena valve set."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "valve_set_last_error_code"

    def __init__(
        self,
        coordinator: GardenaCoordinator,
        device: Device,
    ) -> None:
        """Initialize the valve set error sensor."""
        super().__init__(coordinator, device, "valve_set_last_error_code")

    @property
    def native_value(self) -> str | None:
        """Return the valve set's last error code."""
        device = self._device
        if device is None:
            return None
        if device.valve_set is None:
            return None
        return device.valve_set.last_error_code


# ──────────────────────────────────────────────────────────────────────
# Hub-level diagnostic sensors (coordinator state, not device-bound)
# ──────────────────────────────────────────────────────────────────────


def _hub_device_info(entry: GardenaConfigEntry) -> DeviceInfo:
    """Return device info for the virtual integration hub device."""
    api_type = entry.data.get(CONF_API_TYPE, "gardena")
    hub_name = (
        f"Automower Hub ({entry.title})"
        if api_type == API_TYPE_AUTOMOWER
        else f"Gardena Hub ({entry.title})"
    )
    return DeviceInfo(
        identifiers={(DOMAIN, f"hub_{entry.entry_id}")},
        name=hub_name,
        manufacturer="Husqvarna",
        model="Integration Hub",
        entry_type=DeviceEntryType.SERVICE,
    )


class HubDeviceCountSensor(CoordinatorEntity, SensorEntity):
    """Number of devices currently managed by the coordinator."""

    _attr_has_entity_name = True
    _attr_translation_key = "hub_device_count"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: BaseSmartSystemCoordinator[Any],
        entry: GardenaConfigEntry,
    ) -> None:
        """Initialize the hub device count sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"hub_{entry.entry_id}_device_count"
        self._attr_device_info = _hub_device_info(entry)

    @property
    def native_value(self) -> int:
        """Return the number of devices."""
        return len(self.coordinator.data) if self.coordinator.data else 0


class HubPollingIntervalSensor(CoordinatorEntity, SensorEntity):
    """Current polling interval of the coordinator."""

    _attr_has_entity_name = True
    _attr_translation_key = "hub_polling_interval"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: BaseSmartSystemCoordinator[Any],
        entry: GardenaConfigEntry,
    ) -> None:
        """Initialize the hub polling interval sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"hub_{entry.entry_id}_polling_interval"
        self._attr_device_info = _hub_device_info(entry)

    @property
    def native_value(self) -> float | None:
        """Return the current polling interval in seconds."""
        if self.coordinator.update_interval is None:
            return None
        return self.coordinator.update_interval.total_seconds()
