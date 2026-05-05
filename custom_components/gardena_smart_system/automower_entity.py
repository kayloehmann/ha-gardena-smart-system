"""Base entity class for Automower devices."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aioautomower.exceptions import (
    AutomowerAuthenticationError,
    AutomowerConnectionError,
    AutomowerException,
    AutomowerRequestError,
)
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from aioautomower import AutomowerDevice

from .automower_coordinator import AutomowerCoordinator
from .const import (
    COMMAND_POLL_AFTER_TIMEOUT_SECONDS,
    COMMAND_POLL_INTERVAL_SECONDS,
    DEFAULT_AUTO_RETRY_ON_TIMEOUT,
    DOMAIN,
    OPT_AUTO_RETRY_ON_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

# HTTP statuses where the gateway timed out / was unavailable. The same
# uncertainty as a client-side timeout applies — the request may have reached
# the device anyway.
_GATEWAY_TIMEOUT_STATUSES = frozenset({502, 503, 504})


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
        return (self.coordinator.data or {}).get(self._mower_id)

    @property
    def available(self) -> bool:
        """Return True only when coordinator has data and device is connected."""
        device = self._device
        return False if device is None else super().available and device.is_connected

    async def async_added_to_hass(self) -> None:
        """Seed the availability baseline so the first transition logs."""
        await super().async_added_to_hass()
        self._was_available = self.available

    @callback
    def _handle_coordinator_update(self) -> None:
        """Log device online/offline transitions on every coordinator update."""
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
        expected_state_check: Callable[[], bool] | None = None,
        **kwargs: Any,
    ) -> None:
        """Run an Automower API command through throttle, budget, and exception mapping.

        Mirrors ``GardenaEntity._async_execute_command`` but with
        Automower-specific exception types. See that method for the rationale,
        including the issue #22 poll-after-timeout / opt-in retry behaviour
        triggered by ``expected_state_check``.
        """
        self.coordinator.check_command_throttle()
        self.coordinator.api_budget.increment()
        try:
            await method(*args, **kwargs)
        except AutomowerAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain="gardena_smart_system",
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except AutomowerRequestError as err:
            if err.status in _GATEWAY_TIMEOUT_STATUSES:
                await self._async_handle_timeout(
                    err,
                    method,
                    args,
                    kwargs,
                    expected_state_check=expected_state_check,
                )
                return
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except AutomowerConnectionError as err:
            await self._async_handle_timeout(
                err,
                method,
                args,
                kwargs,
                expected_state_check=expected_state_check,
            )
            return
        except AutomowerException as err:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _async_handle_timeout(
        self,
        err: AutomowerException,
        method: Callable[..., Awaitable[Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        expected_state_check: Callable[[], bool] | None,
    ) -> None:
        """Decide whether an apparent client-side timeout actually failed.

        See ``GardenaEntity._async_handle_timeout`` for the full rationale.
        """
        if expected_state_check is not None and await self._async_wait_for_expected_state(
            expected_state_check
        ):
            _LOGGER.info(
                "%s: command timed out client-side but device reached the expected"
                " state via WebSocket push — treating as success (%s)",
                self._device_name,
                err,
            )
            return

        if self._auto_retry_enabled():
            _LOGGER.info(
                "%s: command timed out and target state not yet observed,"
                " auto-retry is enabled — sending command once more",
                self._device_name,
            )
            try:
                self.coordinator.check_command_throttle()
                self.coordinator.api_budget.increment()
                await method(*args, **kwargs)
            except AutomowerAuthenticationError as retry_err:
                raise ConfigEntryAuthFailed(
                    translation_domain="gardena_smart_system",
                    translation_key="command_failed",
                    translation_placeholders={"error": str(retry_err)},
                ) from retry_err
            except AutomowerException as retry_err:
                if (
                    isinstance(retry_err, AutomowerRequestError)
                    and (retry_err.status in _GATEWAY_TIMEOUT_STATUSES)
                ) or isinstance(retry_err, AutomowerConnectionError):
                    translation_key = "command_timeout"
                else:
                    translation_key = "command_failed"
                raise HomeAssistantError(
                    translation_domain="gardena_smart_system",
                    translation_key=translation_key,
                    translation_placeholders={"error": str(retry_err)},
                ) from retry_err
            else:
                if expected_state_check is not None and await self._async_wait_for_expected_state(
                    expected_state_check
                ):
                    _LOGGER.info(
                        "%s: command succeeded on retry, device reached expected state",
                        self._device_name,
                    )
                    return
                raise HomeAssistantError(
                    translation_domain="gardena_smart_system",
                    translation_key="command_timeout",
                    translation_placeholders={"error": str(err)},
                )

        raise HomeAssistantError(
            translation_domain="gardena_smart_system",
            translation_key="command_timeout",
            translation_placeholders={"error": str(err)},
        ) from err

    async def _async_wait_for_expected_state(
        self,
        expected_state_check: Callable[[], bool],
    ) -> bool:
        """Poll the coordinator-cached state until the target is observed.

        Reads memory only — the WebSocket push from the Husqvarna cloud is
        what actually advances the state.
        """
        if expected_state_check():
            return True
        deadline = asyncio.get_running_loop().time() + COMMAND_POLL_AFTER_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(COMMAND_POLL_INTERVAL_SECONDS)
            if expected_state_check():
                return True
        return False

    def _auto_retry_enabled(self) -> bool:
        """Return whether the user opted into auto-retry on command timeouts."""
        return bool(
            self.coordinator.config_entry.options.get(
                OPT_AUTO_RETRY_ON_TIMEOUT, DEFAULT_AUTO_RETRY_ON_TIMEOUT
            )
        )
