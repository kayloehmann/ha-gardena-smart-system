"""Tests for local gateway id → cloud serial mapping."""

import pytest

from custom_components.gardena_smart_system_ng.local_ids import (
    cloud_serial_from_local_id,
)


@pytest.mark.parametrize(
    ("local_id", "expected_serial"),
    [
        # Verified live against the running cloud integration's device serials.
        ("3034F8EE901EE94000001294", "00004756"),  # Irrigation Control
        ("3034F8319C02BF8000003F81", "00016257"),  # Dual Water Control (right)
        ("3034F8319C02BF800000462E", "00017966"),  # Dual Water Control (left)
    ],
)
def test_known_devices_map_to_cloud_serial(local_id: str, expected_serial: str) -> None:
    """A local SGTIN96 id decodes to the zero-padded 8-digit cloud serial."""
    assert cloud_serial_from_local_id(local_id) == expected_serial


def test_result_is_always_eight_digits() -> None:
    """The cloud serial is zero-padded to a stable 8-character width."""
    serial = cloud_serial_from_local_id("3034F8EE901EE94000001294")
    assert serial is not None
    assert len(serial) == 8
    assert serial.isdigit()


@pytest.mark.parametrize(
    "bad_id",
    [
        "",  # empty
        "not-hex",  # non-hex
        "3034F8EE901E",  # too short (12 hex, not 24)
        "00000000000000000000000000000000",  # invalid SGTIN96 header
    ],
)
def test_undecodable_ids_return_none(bad_id: str) -> None:
    """A non-SGTIN96 id yields None so the caller can skip it, not guess."""
    assert cloud_serial_from_local_id(bad_id) is None
