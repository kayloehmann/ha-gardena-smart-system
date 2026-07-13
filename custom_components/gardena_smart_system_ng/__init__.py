"""The Gardena Smart System integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.importlib import async_import_module

from .base_coordinator import BaseSmartSystemCoordinator
from .const import (
    API_TYPE_AUTOMOWER,
    API_TYPE_GARDENA,
    AUTOMOWER_PLATFORMS,
    CONF_API_TYPE,
    DOMAIN,
    GARDENA_PLATFORMS,
)

if TYPE_CHECKING:
    from .automower_coordinator import AutomowerCoordinator
    from .coordinator import GardenaCoordinator

_LOGGER = logging.getLogger(__name__)

type GardenaConfigEntry = ConfigEntry[BaseSmartSystemCoordinator[Any]]


async def async_setup_entry(hass: HomeAssistant, entry: GardenaConfigEntry) -> bool:
    """Set up Gardena Smart System from a config entry."""
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    session = async_get_clientsession(hass)
    api_type = entry.data.get(CONF_API_TYPE, API_TYPE_GARDENA)

    if api_type == API_TYPE_AUTOMOWER:
        # These submodules are imported lazily (only the branch actually used
        # by this config entry pulls in its client library) so a first-time
        # import can still happen here, on the event loop. CPython's import
        # machinery does blocking file I/O (stat/open/read) to resolve it, so
        # it's routed through HA's dedicated import executor instead of a
        # plain `from .automower_coordinator import AutomowerCoordinator`.
        # See https://github.com/kayloehmann/ha-gardena-smart-system/issues/47
        automower_coordinator_module = await async_import_module(
            hass, f"{__name__}.automower_coordinator"
        )
        automower_coordinator_cls = cast(
            "type[AutomowerCoordinator]",
            automower_coordinator_module.AutomowerCoordinator,
        )
        am_coordinator = automower_coordinator_cls(hass, entry, session)
        await am_coordinator.api_budget.async_load()
        # Load persisted rate-limit state BEFORE first refresh — otherwise a
        # restart while the kill-switch is engaged would still issue an API
        # call (and likely a 429), defeating the kill-switch's whole purpose.
        await am_coordinator.rate_limit_state.async_load()
        await am_coordinator.async_config_entry_first_refresh()
        entry.runtime_data = am_coordinator
        await hass.config_entries.async_forward_entry_setups(entry, AUTOMOWER_PLATFORMS)
    else:
        # Same reasoning as above: `.coordinator` imports `.local_channel`,
        # whose `gardena_smart_local_api` import triggers pydantic's lazy
        # submodule loading — the exact import_module/listdir/read_text
        # blocking calls reported in #47.
        coordinator_module = await async_import_module(hass, f"{__name__}.coordinator")
        coordinator_cls = cast("type[GardenaCoordinator]", coordinator_module.GardenaCoordinator)
        gd_coordinator = coordinator_cls(hass, entry, session)
        await gd_coordinator.api_budget.async_load()
        await gd_coordinator.rate_limit_state.async_load()
        await gd_coordinator.async_config_entry_first_refresh()
        entry.runtime_data = gd_coordinator
        await hass.config_entries.async_forward_entry_setups(entry, GARDENA_PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: GardenaConfigEntry) -> bool:
    """Unload a config entry."""
    api_type = entry.data.get(CONF_API_TYPE, API_TYPE_GARDENA)
    platforms = AUTOMOWER_PLATFORMS if api_type == API_TYPE_AUTOMOWER else GARDENA_PLATFORMS

    coordinator = entry.runtime_data
    await coordinator.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, platforms)


async def _async_options_updated(hass: HomeAssistant, entry: GardenaConfigEntry) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow users to manually remove a device from the device registry."""
    coordinator = config_entry.runtime_data
    # Only allow removal if the device is no longer in the coordinator's data
    if coordinator.data:
        for identifier in device_entry.identifiers:
            if identifier[0] != DOMAIN:
                continue
            serial = identifier[1]
            for device in coordinator.data.values():
                device_serial = getattr(device, "serial_number", None) or getattr(
                    device, "serial", None
                )
                if device_serial == serial:
                    return False
    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entries from older versions."""
    if config_entry.version < 2:
        # v1 → v2: add api_type field (existing entries are all Gardena)
        _LOGGER.debug("Migrating config entry %s from v1 to v2", config_entry.title)
        hass.config_entries.async_update_entry(
            config_entry,
            data={**config_entry.data, CONF_API_TYPE: API_TYPE_GARDENA},
            version=2,
        )
    return True
