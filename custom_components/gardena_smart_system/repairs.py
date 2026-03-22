"""Repair flows for the Gardena Smart System integration."""

from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant

from .const import DOMAIN


class WebSocketReconnectRepairFlow(RepairsFlow):
    """Repair flow that triggers a WebSocket reconnect."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Show confirmation step."""
        if user_input is not None:
            # Trigger a coordinator refresh which will attempt WebSocket reconnect
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                coordinator = getattr(entry, "runtime_data", None)
                if coordinator is not None:
                    await coordinator.async_request_refresh()
            return self.async_create_entry(data={})

        return self.async_show_form(step_id="init")


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str] | None,
) -> RepairsFlow:
    """Create a repair flow for the given issue."""
    return WebSocketReconnectRepairFlow()
