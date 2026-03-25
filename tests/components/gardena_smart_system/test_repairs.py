"""Tests for the Gardena Smart System repair flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

try:
    from tests.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import (
        MockConfigEntry,  # type: ignore[no-redef]
    )

from custom_components.gardena_smart_system.const import DOMAIN
from custom_components.gardena_smart_system.repairs import (
    WebSocketReconnectRepairFlow,
    async_create_fix_flow,
)

from .conftest import ENTRY_DATA

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a config entry added to hass."""
    e = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    e.add_to_hass(hass)
    return e


@pytest.fixture
def coordinator(hass: HomeAssistant, entry: MockConfigEntry) -> MagicMock:
    """Return a mock coordinator attached to the config entry."""
    coord = MagicMock()
    coord.async_request_refresh = AsyncMock()
    entry.runtime_data = coord
    return coord


@pytest.fixture
def flow(hass: HomeAssistant) -> WebSocketReconnectRepairFlow:
    """Return a repair flow bound to hass."""
    f = WebSocketReconnectRepairFlow()
    f.hass = hass
    return f


# ── async_create_fix_flow ────────────────────────────────────────────


class TestAsyncCreateFixFlow:
    """Test the repair flow factory function."""

    async def test_returns_correct_type(self, hass: HomeAssistant) -> None:
        """The factory must return a WebSocketReconnectRepairFlow instance."""
        flow = await async_create_fix_flow(hass, "websocket_connection_failed", None)
        assert isinstance(flow, WebSocketReconnectRepairFlow)

    async def test_accepts_any_issue_id(self, hass: HomeAssistant) -> None:
        """The factory returns a flow regardless of issue_id value."""
        flow = await async_create_fix_flow(hass, "some_other_issue", {"key": "val"})
        assert isinstance(flow, WebSocketReconnectRepairFlow)

    async def test_accepts_none_data(self, hass: HomeAssistant) -> None:
        """The factory handles None data gracefully."""
        flow = await async_create_fix_flow(hass, "websocket_connection_failed", None)
        assert flow is not None


# ── Form step (no user input) ───────────────────────────────────────


class TestRepairFlowFormStep:
    """Test the initial form step shown to the user."""

    async def test_init_without_input_shows_form(self, flow: WebSocketReconnectRepairFlow) -> None:
        """Calling async_step_init without user_input shows the form."""
        result = await flow.async_step_init(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "init"

    async def test_init_with_none_shows_form(self, flow: WebSocketReconnectRepairFlow) -> None:
        """Explicitly passing None also shows the form."""
        result = await flow.async_step_init(None)
        assert result["type"] == "form"


# ── Confirm step (with user input) ──────────────────────────────────


class TestRepairFlowConfirmStep:
    """Test the confirmation step that triggers coordinator refreshes."""

    async def test_confirm_creates_entry(
        self,
        flow: WebSocketReconnectRepairFlow,
        entry: MockConfigEntry,
        coordinator: MagicMock,
    ) -> None:
        """Confirming the flow creates an entry (completes the repair)."""
        result = await flow.async_step_init(user_input={})
        assert result["type"] == "create_entry"
        assert result["data"] == {}

    async def test_confirm_triggers_refresh(
        self,
        flow: WebSocketReconnectRepairFlow,
        entry: MockConfigEntry,
        coordinator: MagicMock,
    ) -> None:
        """Confirming calls async_request_refresh on the coordinator."""
        await flow.async_step_init(user_input={})
        coordinator.async_request_refresh.assert_awaited_once()

    async def test_confirm_refreshes_multiple_entries(
        self, hass: HomeAssistant
    ) -> None:
        """All config entries with runtime_data get refreshed."""
        coordinators = []
        for i in range(3):
            e = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
            e.add_to_hass(hass)
            coord = MagicMock()
            coord.async_request_refresh = AsyncMock()
            e.runtime_data = coord
            coordinators.append(coord)

        flow = WebSocketReconnectRepairFlow()
        flow.hass = hass

        await flow.async_step_init(user_input={})

        for coord in coordinators:
            coord.async_request_refresh.assert_awaited_once()

    async def test_confirm_skips_entries_without_runtime_data(
        self, hass: HomeAssistant
    ) -> None:
        """Entries that have no runtime_data are silently skipped."""
        # Entry WITH coordinator
        entry_with = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
        entry_with.add_to_hass(hass)
        coord = MagicMock()
        coord.async_request_refresh = AsyncMock()
        entry_with.runtime_data = coord

        # Entry WITHOUT coordinator (not yet set up)
        entry_without = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
        entry_without.add_to_hass(hass)
        # Do NOT set runtime_data — getattr(..., None) should return None

        flow = WebSocketReconnectRepairFlow()
        flow.hass = hass

        # Should not raise
        result = await flow.async_step_init(user_input={})
        assert result["type"] == "create_entry"
        coord.async_request_refresh.assert_awaited_once()

    async def test_confirm_with_no_entries(self, hass: HomeAssistant) -> None:
        """If no config entries exist, confirm still succeeds."""
        flow = WebSocketReconnectRepairFlow()
        flow.hass = hass

        result = await flow.async_step_init(user_input={})
        assert result["type"] == "create_entry"


# ── Issue creation & deletion integration ────────────────────────────


class TestRepairIssueLifecycle:
    """Test issue creation and clearing via the coordinator."""

    def test_issue_attributes(self, hass: HomeAssistant) -> None:
        """Verify the repair issue has the expected attributes."""
        ir.async_create_issue(
            hass,
            DOMAIN,
            "websocket_connection_failed",
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="websocket_connection_failed",
        )

        issue_reg = ir.async_get(hass)
        issue = issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed")
        assert issue is not None
        assert issue.is_fixable is True
        assert issue.is_persistent is False
        assert issue.severity == ir.IssueSeverity.WARNING
        assert issue.translation_key == "websocket_connection_failed"

    def test_delete_nonexistent_issue_does_not_raise(self, hass: HomeAssistant) -> None:
        """Deleting an issue that doesn't exist should not crash."""
        # Should be a no-op
        ir.async_delete_issue(hass, DOMAIN, "websocket_connection_failed")

    def test_create_issue_idempotent(self, hass: HomeAssistant) -> None:
        """Creating the same issue twice does not raise or duplicate."""
        for _ in range(3):
            ir.async_create_issue(
                hass,
                DOMAIN,
                "websocket_connection_failed",
                is_fixable=True,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="websocket_connection_failed",
            )

        issue_reg = ir.async_get(hass)
        issue = issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed")
        assert issue is not None

    def test_delete_clears_issue(self, hass: HomeAssistant) -> None:
        """After deletion, the issue is gone."""
        ir.async_create_issue(
            hass,
            DOMAIN,
            "websocket_connection_failed",
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="websocket_connection_failed",
        )
        ir.async_delete_issue(hass, DOMAIN, "websocket_connection_failed")

        issue_reg = ir.async_get(hass)
        assert issue_reg.async_get_issue(DOMAIN, "websocket_connection_failed") is None
