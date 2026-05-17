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
    COMMAND_RETRY_ATTEMPTS,
    DOMAIN,
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
        """Run an API command with retry-until-confirmed semantics.

        The Gardena cloud is the source of failure here, not us. Its gateway
        regularly returns 502/503/504 at the top of the hour (when many users'
        schedules fire), and a 504 can mean either "request never reached the
        device" or "device got it, response was lost". The integration cannot
        distinguish those without WebSocket confirmation.

        Strategy: send the command, then — only if the HTTP call returned a
        gateway timeout / connection error — wait briefly for the WebSocket to
        push the expected state. If it does, the command landed; treat as
        success. If it does not, send the command again. Up to
        ``COMMAND_RETRY_ATTEMPTS`` tries total before raising
        ``command_timeout``.

        Idempotency assumption: every command this integration sends is
        idempotent at the device level. ``START_DONT_OVERRIDE`` on a mowing
        mower is a no-op; ``PARK_*`` on a parked mower is a no-op; valve
        open/close and socket on/off are state-set operations. Retrying after
        a 504 cannot cause unwanted double execution.

        Polling reads the in-memory coordinator only — no extra REST calls.
        The API budget counts each attempt that actually fires.

        Non-timeout errors (auth, deterministic 4xx, other library errors)
        short-circuit immediately — there is nothing a retry would fix.
        """
        last_timeout_err: GardenaException | None = None

        for attempt in range(COMMAND_RETRY_ATTEMPTS):
            is_last_attempt = attempt == COMMAND_RETRY_ATTEMPTS - 1
            self.coordinator.check_command_throttle()
            self.coordinator.api_budget.increment()
            # Capture the WebSocket push marker *before* sending. Only a push
            # that arrives after this point proves the command landed; the
            # cached state may still hold a stale activity from a previous
            # cycle (e.g. OK_SEARCHING/OK_LEAVING) that would otherwise be
            # mistaken for success.
            ws_marker = self.coordinator.ws_push_at(self._device_id)
            try:
                await method(*args, **kwargs)
            except GardenaAuthenticationError as err:
                raise ConfigEntryAuthFailed(
                    translation_domain="gardena_smart_system_ng",
                    translation_key="command_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
            except GardenaRequestError as err:
                if err.status not in _GATEWAY_TIMEOUT_STATUSES:
                    raise HomeAssistantError(
                        translation_domain="gardena_smart_system_ng",
                        translation_key="command_failed",
                        translation_placeholders={"error": str(err)},
                    ) from err
                last_timeout_err = err
            except GardenaConnectionError as err:
                last_timeout_err = err
            except GardenaException as err:
                raise HomeAssistantError(
                    translation_domain="gardena_smart_system_ng",
                    translation_key="command_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
            else:
                # HTTP returned cleanly. Trust it.
                return

            # Got a gateway timeout / connection error. The device may still
            # have received the command — wait for a WebSocket-pushed state
            # confirmation before deciding to retry.
            if expected_state_check is not None and await self._async_wait_for_expected_state(
                expected_state_check, ws_marker
            ):
                _LOGGER.info(
                    "%s: attempt %d timed out client-side but device reached"
                    " the expected state via WebSocket push — treating as"
                    " success (%s)",
                    self._device_name,
                    attempt + 1,
                    last_timeout_err,
                )
                return

            if not is_last_attempt:
                _LOGGER.info(
                    "%s: attempt %d/%d timed out and target state not yet observed, retrying (%s)",
                    self._device_name,
                    attempt + 1,
                    COMMAND_RETRY_ATTEMPTS,
                    last_timeout_err,
                )

        raise HomeAssistantError(
            translation_domain="gardena_smart_system_ng",
            translation_key="command_timeout",
            translation_placeholders={"error": str(last_timeout_err)},
        ) from last_timeout_err

    async def _async_wait_for_expected_state(
        self,
        expected_state_check: Callable[[], bool],
        ws_marker: float,
    ) -> bool:
        """Wait for a *fresh* WebSocket push that confirms the target state.

        Reads memory only — the WebSocket push from the Gardena cloud is what
        actually advances the state. ``ws_marker`` is the per-device push
        timestamp captured immediately before the command was sent.

        A confirmation requires **both**:

        1. a WebSocket push for this device that arrived *after* the command
           was sent (``ws_push_at > ws_marker``), and
        2. ``expected_state_check()`` returning truthy.

        Requiring the fresh push is what fixes the silent-failure class of
        bugs (issue #27): after a 504 the cached coordinator state can still
        hold a stale activity from the previous cycle (``OK_SEARCHING`` /
        ``OK_LEAVING`` are both in the "mowing" set). The old code trusted
        that cached state directly and reported a false-positive success — the
        mower never started and nothing was logged above INFO. Without a fresh
        confirming push we now fall through to a retry, and ultimately to a
        visible ``command_timeout`` instead of a silent no-op.

        Returns ``True`` if a fresh confirming push is observed within
        COMMAND_POLL_AFTER_TIMEOUT_SECONDS, ``False`` otherwise.
        """

        def confirmed() -> bool:
            return (
                self.coordinator.ws_push_at(self._device_id) > ws_marker and expected_state_check()
            )

        # Initial check before the first sleep — a push may already have
        # arrived by the time the API call returned. Still gated on the
        # fresh-push marker, so stale cache cannot satisfy it.
        if confirmed():
            return True
        deadline = asyncio.get_running_loop().time() + COMMAND_POLL_AFTER_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(COMMAND_POLL_INTERVAL_SECONDS)
            if confirmed():
                return True
        return False
