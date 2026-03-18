"""Base entity class for Gardena Smart System entities."""

from __future__ import annotations

from aiogardenasmart import Device

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GardenaCoordinator


class GardenaEntity(CoordinatorEntity[GardenaCoordinator]):
    """Base class for all Gardena Smart System entities.

    Provides:
    - has_entity_name = True  (bronze: has-entity-name)
    - Stable unique IDs based on device serial + service + attribute
    - Device info wired to the HA device registry (gold: devices)
    - Availability tied to device RF link state (silver: entity-unavailable)
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GardenaCoordinator,
        device: Device,
        unique_id_suffix: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._device_id = device.device_id
        # Unique ID uses serial for stability across re-pairing (bronze: entity-unique-id)
        self._attr_unique_id = f"{device.serial}_{unique_id_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.serial)},
            name=device.name,
            manufacturer="Gardena",
            model=device.model,
            serial_number=device.serial,
        )

    @property
    def _device(self) -> Device | None:
        """Return the current device state from the coordinator."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._device_id)

    @property
    def available(self) -> bool:
        """Return True only when coordinator has data and device is RF-online."""
        device = self._device
        if device is None:
            return False
        return super().available and device.is_online
