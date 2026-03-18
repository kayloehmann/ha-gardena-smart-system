"""The Gardena Smart System integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import PLATFORMS
from .coordinator import GardenaCoordinator

_LOGGER = logging.getLogger(__name__)

type GardenaConfigEntry = ConfigEntry[GardenaCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: GardenaConfigEntry) -> bool:
    """Set up Gardena Smart System from a config entry."""
    session = async_get_clientsession(hass)
    coordinator = GardenaCoordinator(hass, entry, session)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GardenaConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: GardenaCoordinator = entry.runtime_data
    await coordinator.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
