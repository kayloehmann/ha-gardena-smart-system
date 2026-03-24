"""The Gardena Smart System integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_TYPE_AUTOMOWER,
    API_TYPE_GARDENA,
    AUTOMOWER_PLATFORMS,
    CONF_API_TYPE,
    DOMAIN,
    GARDENA_PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)

type GardenaConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: GardenaConfigEntry) -> bool:
    """Set up Gardena Smart System from a config entry."""
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    session = async_get_clientsession(hass)
    api_type = entry.data.get(CONF_API_TYPE, API_TYPE_GARDENA)

    if api_type == API_TYPE_AUTOMOWER:
        from .automower_coordinator import AutomowerCoordinator

        am_coordinator = AutomowerCoordinator(hass, entry, session)
        await am_coordinator.async_config_entry_first_refresh()
        entry.runtime_data = am_coordinator
        await hass.config_entries.async_forward_entry_setups(entry, AUTOMOWER_PLATFORMS)
    else:
        from .coordinator import GardenaCoordinator

        gd_coordinator = GardenaCoordinator(hass, entry, session)
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
