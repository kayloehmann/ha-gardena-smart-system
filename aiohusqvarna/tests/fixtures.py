"""Shared test fixtures and API response payloads for aiohusqvarna tests."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Auth fixtures (reused from aiogardenasmart TOKEN_RESPONSE format)
# ---------------------------------------------------------------------------

TOKEN_RESPONSE = {
    "access_token": "test-access-token",
    "refresh_token": "test-refresh-token",
    "expires_in": 3600,
}

# ---------------------------------------------------------------------------
# Mower fixtures
# ---------------------------------------------------------------------------

MOWER_ID = "12345678-abcd-ef01-2345-6789abcdef01"
WORK_AREA_ID = 123456
STAY_OUT_ZONE_ID = "zzzz-zone-uuid"

MOWER_ATTRIBUTES = {
    "system": {
        "name": "Test Automower 420",
        "model": "AUTOMOWER® 420",
        "serialNumber": "SN-AM-001",
    },
    "battery": {"batteryPercent": 75},
    "mower": {
        "mode": "MAIN_AREA",
        "activity": "MOWING",
        "state": "IN_OPERATION",
        "errorCode": 0,
        "errorCodeTimestamp": 0,
        "isErrorConfirmable": False,
    },
    "calendar": {
        "tasks": [
            {
                "start": 480,
                "duration": 120,
                "monday": True,
                "tuesday": True,
                "wednesday": True,
                "thursday": True,
                "friday": True,
                "saturday": False,
                "sunday": False,
            }
        ]
    },
    "planner": {
        "nextStartTimestamp": 0,
        "override": {"action": "NOT_ACTIVE"},
        "restrictedReason": "NONE",
    },
    "metadata": {"connected": True, "statusTimestamp": 1700000000000},
    "positions": [{"latitude": 48.1234, "longitude": 11.5678}],
    "statistics": {
        "cuttingBladeUsageTime": 10,
        "numberOfChargingCycles": 5,
        "numberOfCollisions": 2,
        "totalChargingTime": 300,
        "totalCuttingTime": 600,
        "totalDriveDistance": 1500,
        "totalRunningTime": 900,
        "totalSearchingTime": 60,
    },
    "settings": {
        "cuttingHeight": 5,
        "headlight": {"mode": "EVENING_ONLY"},
    },
    "capabilities": {
        "headlights": True,
        "workAreas": True,
        "stayOutZones": True,
        "position": True,
        "canConfirmError": True,
    },
    "workAreas": [
        {
            "workAreaId": WORK_AREA_ID,
            "name": "Front Lawn",
            "cuttingHeight": 50,
            "enabled": True,
        }
    ],
    "stayOutZones": {
        "zones": {
            STAY_OUT_ZONE_ID: {
                "name": "Flower Bed",
                "enabled": True,
            }
        }
    },
}

MOWER_ITEM = {
    "id": MOWER_ID,
    "type": "mower",
    "attributes": MOWER_ATTRIBUTES,
}

MOWERS_RESPONSE = {"data": [MOWER_ITEM]}

MOWER_RESPONSE = {"data": MOWER_ITEM}
