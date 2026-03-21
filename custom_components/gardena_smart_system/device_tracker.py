"""Device tracker platform for the Gardena Smart System integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GardenaConfigEntry
from .automower_device_tracker import async_setup_entry as automower_setup
from .const import API_TYPE_AUTOMOWER, CONF_API_TYPE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GardenaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up device tracker entities from a config entry."""
    if entry.data.get(CONF_API_TYPE) == API_TYPE_AUTOMOWER:
        await automower_setup(hass, entry, async_add_entities)
