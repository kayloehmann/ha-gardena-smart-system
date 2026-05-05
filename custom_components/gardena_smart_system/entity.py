"""Base entity class for Gardena Smart System entities."""

from __future__ import annotations

import asyncio
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

from .const import (
    COMMAND_POLL_AFTER_TIMEOUT_SECONDS,
    COMMAND_POLL_INTERVAL_SECONDS,
    DEFAULT_AUTO_RETRY_ON_TIMEOUT,
    DOMAIN,
    OPT_AUTO_RETRY_ON_TIMEOUT,
)
from .coordinator import GardenaCoordinator

_LOGGER = logging.getLogger(__name__)

# HTTP statuses where the gateway timed out / was unavailable. The same
# uncertainty as a client-side timeout applies — the request may have reached
# the device anyway.
_GATEWAY_TIMEOUT_STATUSES = frozenset({502, 503, 504})


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
        expected_state_check: Callable[[], bool] | None = None,
        **kwargs: Any,
    ) -> None:
        """Run an API command through throttle, budget, and exception mapping.

        Each callsite previously duplicated the throttle/increment/try-except
        boilerplate. Centralising it here keeps the command path uniform: the
        budget is counted *before* the await (pessimistic accounting — see
        v1.10.4 fix), auth failures trigger reauth, transient upstream timeouts
        surface a "may have happened, check state" message, and all other API
        errors surface as translated HomeAssistantError.

        ``expected_state_check`` (issue #22): a zero-arg callable that returns
        ``True`` once the coordinator's cached state reflects the command's
        target. When a client-side timeout / 502 / 503 / 504 hits — situations
        where the request may still have been processed server-side — the
        method polls this lambda for up to COMMAND_POLL_AFTER_TIMEOUT_SECONDS
        before re-raising. The coordinator is updated by the WebSocket push;
        polling here reads memory only, no extra REST calls.

        If ``auto_retry_on_timeout`` is enabled in the config entry options
        and polling yields no state change, the command is sent exactly once
        more before giving up.
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
        except GardenaConnectionError as err:
            await self._async_handle_timeout(
                err,
                method,
                args,
                kwargs,
                expected_state_check=expected_state_check,
            )
            return
        except GardenaException as err:
            raise HomeAssistantError(
                translation_domain="gardena_smart_system",
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _async_handle_timeout(
        self,
        err: GardenaException,
        method: Callable[..., Awaitable[Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        expected_state_check: Callable[[], bool] | None,
    ) -> None:
        """Decide whether an apparent client-side timeout actually failed.

        Implements the issue #22 recovery path: poll the coordinator for the
        expected target state, then optionally retry once when configured.
        Always raises ``HomeAssistantError`` with the ``command_timeout``
        translation key when the device cannot be confirmed in the target
        state.
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
            except GardenaAuthenticationError as retry_err:
                raise ConfigEntryAuthFailed(
                    translation_domain="gardena_smart_system",
                    translation_key="command_failed",
                    translation_placeholders={"error": str(retry_err)},
                ) from retry_err
            except GardenaException as retry_err:
                # Retry hit a fresh error: surface the most informative key.
                # 5xx/connection errors keep the timeout messaging; everything
                # else is a deterministic failure.
                if (
                    isinstance(retry_err, GardenaRequestError)
                    and (retry_err.status in _GATEWAY_TIMEOUT_STATUSES)
                ) or isinstance(retry_err, GardenaConnectionError):
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
                # Retry returned cleanly but we still cannot confirm the
                # device state. Mirror the original timeout so the user knows
                # to check.
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

        Reads memory only — the WebSocket push from the Gardena cloud is what
        actually advances the state. Returns ``True`` if the lambda returns
        truthy within COMMAND_POLL_AFTER_TIMEOUT_SECONDS, ``False`` otherwise.
        """
        # Initial check before the first sleep — the WebSocket may already
        # have pushed the new state by the time the API call returns.
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
