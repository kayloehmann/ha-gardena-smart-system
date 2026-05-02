"""Base entity class for Gardena Smart System entities."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from aiogardenasmart import (
    Device,
    GardenaAuthenticationError,
    GardenaConnectionError,
    GardenaException,
    GardenaRequestError,
)

from .const import DOMAIN
from .coordinator import GardenaCoordinator

_LOGGER = logging.getLogger(__name__)


def resolve_zone_placeholder(device: Device, service_id: str) -> str:
    """Return the zone display name for translation placeholders.

    Multi-valve devices (Irrigation Control) return " Rasen vorne" or " Zone 1".
    Single-valve devices (Smart Water Control) return "" so the name has no suffix.
    The leading space is intentional — translation strings use "Name{zone}".
    """
    zone = service_id.split(":")[-1] if ":" in service_id else ""
    if not zone:
        return ""
    valve = device.valves.get(service_id)
    name = valve.name if valve and valve.name else f"Zone {zone}"
    return f" {name}"


class GardenaEntity(CoordinatorEntity[GardenaCoordinator]):
    """Base class for all Gardena Smart System entities.

    Provides:
    - has_entity_name = True  (bronze: has-entity-name)
    - Stable unique IDs based on device serial + service + attribute
    - Device info wired to the HA device registry (gold: devices)
    - Availability tied to device RF link state (silver: entity-unavailable)
    - Logs device online/offline transitions (silver: log-when-unavailable)
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
        self._device_name = device.name
        self._was_available: bool | None = None
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
        return (self.coordinator.data or {}).get(self._device_id)

    @property
    def available(self) -> bool:
        """Return True only when coordinator has data and device is RF-online."""
        device = self._device
        return False if device is None else super().available and device.is_online

    async def async_added_to_hass(self) -> None:
        """Seed the availability baseline so the first transition logs."""
        await super().async_added_to_hass()
        self._was_available = self.available

    @callback
    def _handle_coordinator_update(self) -> None:
        """Log device online/offline transitions on every coordinator update.

        Kept out of the ``available`` property so that read-heavy callers
        (every HA attribute read) do not trigger state mutation and log
        calls. Called once per coordinator update — exactly when device
        availability can change.
        """
        current = self.available
        if self._was_available is not None and current != self._was_available:
            if current:
                _LOGGER.info("Device %s is back online", self._device_name)
            else:
                _LOGGER.warning("Device %s is offline", self._device_name)
        self._was_available = current
        super()._handle_coordinator_update()

    async def _async_execute_command(
        self,
        method: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Run an API command through throttle, budget, and exception mapping.

        Each callsite previously duplicated the throttle/increment/try-except
        boilerplate. Centralising it here keeps the command path uniform: the
        budget is counted *before* the await (pessimistic accounting — see
        v1.10.4 fix), auth failures trigger reauth, transient upstream timeouts
        surface a "may have happened, check state" message, and all other API
        errors surface as translated HomeAssistantError.
        """
        self.coordinator.check_command_throttle()
        self.coordinator.api_budget.increment()
        try:
            await method(*args, **kwargs)
        except GardenaAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain="gardena_smart_system",
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except GardenaRequestError as err:
            # 502/503/504 from the upstream gateway: the request reached the
            # Gardena edge but the backend timed out or was unavailable. The
            # command may or may not have been processed — surface that
            # uncertainty so users check device state instead of blindly
            # retrying.
            translation_key = (
                "command_timeout" if err.status in (502, 503, 504) else "command_failed"
            )
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key=translation_key,
                translation_placeholders={"error": str(err)},
            ) from err
        except GardenaConnectionError as err:
            # Network-level failure (DNS, connection refused, client timeout).
            # Same uncertainty as 504 — a client-side timeout can still race a
            # successful server-side write.
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="command_timeout",
                translation_placeholders={"error": str(err)},
            ) from err
        except GardenaException as err:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
