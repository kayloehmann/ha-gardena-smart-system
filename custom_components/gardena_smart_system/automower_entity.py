"""Base entity class for Automower devices."""

from __future__ import annotations

import logging

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from aioautomower import AutomowerDevice

from .automower_coordinator import AutomowerCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class AutomowerEntity(CoordinatorEntity[AutomowerCoordinator]):
    """Base class for all Automower entities.

    Provides:
    - has_entity_name = True
    - Stable unique IDs based on serial number + suffix
    - Device info wired to the HA device registry
    - Availability tied to cloud connectivity
    - Logs device online/offline transitions (silver: log-when-unavailable)
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AutomowerCoordinator,
        device: AutomowerDevice,
        unique_id_suffix: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._mower_id = device.mower_id
        self._device_name = device.name
        self._was_available: bool | None = None
        self._attr_unique_id = f"{device.serial_number}_{unique_id_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.serial_number)},
            name=device.name,
            manufacturer="Husqvarna",
            model=device.model,
            serial_number=device.serial_number,
        )

    @property
    def _device(self) -> AutomowerDevice | None:
        """Return the current device state from the coordinator."""
        if self.coordinator.data is None:
            return None  # type: ignore[unreachable]
        return self.coordinator.data.get(self._mower_id)

    @property
    def available(self) -> bool:
        """Return True only when coordinator has data and device is connected."""
        device = self._device
        is_available = False if device is None else super().available and device.is_connected

        if self._was_available is not None and is_available != self._was_available:
            if is_available:
                _LOGGER.info("Device %s is back online", self._device_name)
            else:
                _LOGGER.warning("Device %s is offline", self._device_name)
        self._was_available = is_available

        return is_available
