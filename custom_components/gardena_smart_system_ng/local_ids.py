"""Mapping between local gateway device ids and cloud device serials.

The local GARDENA smart Gateway identifies devices by their 24-hex-character
SGTIN96 EPC (e.g. ``3034F8EE901EE94000001294``). The cloud API — and therefore
every existing HA entity/device in this integration — identifies the same
physical device by its printed serial number, zero-padded to 8 digits
(e.g. ``00004756``).

The bridge is the SGTIN96 *serial* field: decoding the local id yields the
integer serial, which zero-padded to 8 digits equals the cloud serial. Verified
live against three devices (Irrigation Control 4756→00004756, two Dual Water
Controls 16257→00016257 / 17966→00017966). Decoding is done by the official
``gardena-smart-local-api`` library, which this integration already depends on.
"""

from __future__ import annotations

import logging

from gardena_smart_local_api.sgtin96 import SGTIN96Info

from .const import LOCAL_SERIAL_PAD_WIDTH

_LOGGER = logging.getLogger(__name__)


def cloud_serial_from_local_id(local_id: str) -> str | None:
    """Return the cloud device serial for a local gateway device id.

    ``local_id`` is the gateway's 24-hex-character SGTIN96 EPC. Returns the
    zero-padded serial string used as the cloud-side device identifier, or
    ``None`` if ``local_id`` is not a decodable SGTIN96 (in which case the
    caller should skip the device rather than guess a mapping).
    """
    try:
        info = SGTIN96Info.from_hex(local_id)
    except ValueError as err:
        _LOGGER.debug("Cannot decode local device id %s as SGTIN96: %s", local_id, err)
        return None
    return f"{info.serial:0{LOCAL_SERIAL_PAD_WIDTH}d}"
