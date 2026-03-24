"""Repair flows for the Gardena Smart System integration."""

from __future__ import annotations

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant


class WebSocketReconnectRepairFlow(RepairsFlow):
    """Repair flow that triggers a coordinator refresh to reconnect the WebSocket."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the repair flow."""
        if user_input is not None:
            # Trigger a refresh on all config entries to attempt reconnection
            for entry in self.hass.config_entries.async_entries("gardena_smart_system"):
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
