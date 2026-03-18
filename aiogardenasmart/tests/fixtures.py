"""Shared test fixtures and API response payloads."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Auth fixtures
# ---------------------------------------------------------------------------

TOKEN_RESPONSE = {
    "access_token": "test-access-token",
    "refresh_token": "test-refresh-token",
    "expires_in": 3600,
}

TOKEN_RESPONSE_NO_REFRESH = {
    "access_token": "test-access-token",
    "expires_in": 3600,
}

# ---------------------------------------------------------------------------
# Location fixtures
# ---------------------------------------------------------------------------

LOCATION_ID = "753aecac-4c46-470e-aa96-d92436f11e77"
LOCATION_NAME = "My Garden"

LOCATIONS_RESPONSE = {
    "data": [
        {
            "id": LOCATION_ID,
            "type": "LOCATION",
            "attributes": {"name": {"value": LOCATION_NAME}},
        }
    ]
}

# ---------------------------------------------------------------------------
# Device fixtures — one of each type
# ---------------------------------------------------------------------------

SENSOR_DEVICE_ID = "sensor-device-uuid"
WATER_CONTROL_DEVICE_ID = "water-control-uuid"
IRRIGATION_DEVICE_ID = "irrigation-uuid"
POWER_SOCKET_DEVICE_ID = "power-socket-uuid"
MOWER_DEVICE_ID = "mower-device-uuid"

# Smart Sensor device
SENSOR_LOCATION_RESPONSE = {
    "data": {
        "id": LOCATION_ID,
        "type": "LOCATION",
        "attributes": {"name": {"value": LOCATION_NAME}},
        "relationships": {
            "devices": {
                "data": [{"id": SENSOR_DEVICE_ID, "type": "DEVICE"}]
            }
        },
    },
    "included": [
        {
            "id": SENSOR_DEVICE_ID,
            "type": "DEVICE",
            "relationships": {
                "location": {"data": {"id": LOCATION_ID, "type": "LOCATION"}},
                "services": {
                    "data": [
                        {"id": SENSOR_DEVICE_ID, "type": "SENSOR"},
                        {"id": SENSOR_DEVICE_ID, "type": "COMMON"},
                    ]
                },
            },
        },
        {
            "id": SENSOR_DEVICE_ID,
            "type": "COMMON",
            "attributes": {
                "name": {"value": "My Sensor"},
                "serial": {"value": "SN001"},
                "modelType": {"value": "GARDENA smart Sensor"},
                "batteryLevel": {"value": 85, "timestamp": "2024-01-01T00:00:00Z"},
                "batteryState": {"value": "OK"},
                "rfLinkLevel": {"value": 60, "timestamp": "2024-01-01T00:00:00Z"},
                "rfLinkState": {"value": "ONLINE"},
            },
            "relationships": {"device": {"data": {"id": SENSOR_DEVICE_ID, "type": "DEVICE"}}},
        },
        {
            "id": SENSOR_DEVICE_ID,
            "type": "SENSOR",
            "attributes": {
                "soilHumidity": {"value": 42, "timestamp": "2024-01-01T00:00:00Z"},
                "soilTemperature": {"value": 18.5, "timestamp": "2024-01-01T00:00:00Z"},
                "ambientTemperature": {"value": 22.1, "timestamp": "2024-01-01T00:00:00Z"},
                "lightIntensity": {"value": 15000, "timestamp": "2024-01-01T00:00:00Z"},
            },
            "relationships": {"device": {"data": {"id": SENSOR_DEVICE_ID, "type": "DEVICE"}}},
        },
    ],
}

# Smart Water Control (single valve)
WATER_CONTROL_LOCATION_RESPONSE = {
    "data": {
        "id": LOCATION_ID,
        "type": "LOCATION",
        "attributes": {"name": {"value": LOCATION_NAME}},
        "relationships": {
            "devices": {
                "data": [{"id": WATER_CONTROL_DEVICE_ID, "type": "DEVICE"}]
            }
        },
    },
    "included": [
        {
            "id": WATER_CONTROL_DEVICE_ID,
            "type": "DEVICE",
            "relationships": {
                "location": {"data": {"id": LOCATION_ID, "type": "LOCATION"}},
                "services": {
                    "data": [
                        {"id": WATER_CONTROL_DEVICE_ID, "type": "VALVE_SET"},
                        {"id": f"{WATER_CONTROL_DEVICE_ID}:1", "type": "VALVE"},
                        {"id": WATER_CONTROL_DEVICE_ID, "type": "COMMON"},
                    ]
                },
            },
        },
        {
            "id": WATER_CONTROL_DEVICE_ID,
            "type": "COMMON",
            "attributes": {
                "name": {"value": "Water Control"},
                "serial": {"value": "WC001"},
                "modelType": {"value": "GARDENA smart Water Control"},
                "batteryLevel": {"value": 100, "timestamp": "2024-01-01T00:00:00Z"},
                "batteryState": {"value": "OK"},
                "rfLinkLevel": {"value": 80},
                "rfLinkState": {"value": "ONLINE"},
            },
            "relationships": {"device": {"data": {"id": WATER_CONTROL_DEVICE_ID, "type": "DEVICE"}}},
        },
        {
            "id": WATER_CONTROL_DEVICE_ID,
            "type": "VALVE_SET",
            "attributes": {
                "state": {"value": "OK"},
                "lastErrorCode": {"value": "NO_MESSAGE"},
            },
            "relationships": {"device": {"data": {"id": WATER_CONTROL_DEVICE_ID, "type": "DEVICE"}}},
        },
        {
            "id": f"{WATER_CONTROL_DEVICE_ID}:1",
            "type": "VALVE",
            "attributes": {
                "name": {"value": "My Valve"},
                "activity": {"value": "CLOSED"},
                "state": {"value": "OK"},
                "duration": {"value": 0},
                "lastErrorCode": {"value": "NO_MESSAGE"},
            },
            "relationships": {"device": {"data": {"id": WATER_CONTROL_DEVICE_ID, "type": "DEVICE"}}},
        },
    ],
}

# Smart Irrigation Control (6 valves)
IRRIGATION_LOCATION_RESPONSE = {
    "data": {
        "id": LOCATION_ID,
        "type": "LOCATION",
        "attributes": {"name": {"value": LOCATION_NAME}},
        "relationships": {
            "devices": {
                "data": [{"id": IRRIGATION_DEVICE_ID, "type": "DEVICE"}]
            }
        },
    },
    "included": [
        {
            "id": IRRIGATION_DEVICE_ID,
            "type": "DEVICE",
            "relationships": {
                "location": {"data": {"id": LOCATION_ID, "type": "LOCATION"}},
                "services": {
                    "data": [
                        {"id": IRRIGATION_DEVICE_ID, "type": "VALVE_SET"},
                        *[
                            {"id": f"{IRRIGATION_DEVICE_ID}:{i}", "type": "VALVE"}
                            for i in range(1, 7)
                        ],
                        {"id": IRRIGATION_DEVICE_ID, "type": "COMMON"},
                    ]
                },
            },
        },
        {
            "id": IRRIGATION_DEVICE_ID,
            "type": "COMMON",
            "attributes": {
                "name": {"value": "Irrigation Control"},
                "serial": {"value": "IC001"},
                "modelType": {"value": "GARDENA smart Irrigation Control"},
                "batteryLevel": {"value": 90},
                "batteryState": {"value": "OK"},
                "rfLinkLevel": {"value": 70},
                "rfLinkState": {"value": "ONLINE"},
            },
            "relationships": {"device": {"data": {"id": IRRIGATION_DEVICE_ID, "type": "DEVICE"}}},
        },
        {
            "id": IRRIGATION_DEVICE_ID,
            "type": "VALVE_SET",
            "attributes": {"state": {"value": "OK"}, "lastErrorCode": {"value": "NO_MESSAGE"}},
            "relationships": {"device": {"data": {"id": IRRIGATION_DEVICE_ID, "type": "DEVICE"}}},
        },
        *[
            {
                "id": f"{IRRIGATION_DEVICE_ID}:{i}",
                "type": "VALVE",
                "attributes": {
                    "name": {"value": f"Zone {i}"},
                    "activity": {"value": "CLOSED"},
                    "state": {"value": "OK"},
                    "duration": {"value": 0},
                    "lastErrorCode": {"value": "NO_MESSAGE"},
                },
                "relationships": {
                    "device": {"data": {"id": IRRIGATION_DEVICE_ID, "type": "DEVICE"}}
                },
            }
            for i in range(1, 7)
        ],
    ],
}

# Power Socket
POWER_SOCKET_LOCATION_RESPONSE = {
    "data": {
        "id": LOCATION_ID,
        "type": "LOCATION",
        "attributes": {"name": {"value": LOCATION_NAME}},
        "relationships": {
            "devices": {"data": [{"id": POWER_SOCKET_DEVICE_ID, "type": "DEVICE"}]}
        },
    },
    "included": [
        {
            "id": POWER_SOCKET_DEVICE_ID,
            "type": "DEVICE",
            "relationships": {
                "location": {"data": {"id": LOCATION_ID, "type": "LOCATION"}},
                "services": {
                    "data": [
                        {"id": POWER_SOCKET_DEVICE_ID, "type": "POWER_SOCKET"},
                        {"id": POWER_SOCKET_DEVICE_ID, "type": "COMMON"},
                    ]
                },
            },
        },
        {
            "id": POWER_SOCKET_DEVICE_ID,
            "type": "COMMON",
            "attributes": {
                "name": {"value": "Power Socket"},
                "serial": {"value": "PS001"},
                "modelType": {"value": "GARDENA smart Power Socket"},
                "rfLinkLevel": {"value": 90},
                "rfLinkState": {"value": "ONLINE"},
            },
            "relationships": {"device": {"data": {"id": POWER_SOCKET_DEVICE_ID, "type": "DEVICE"}}},
        },
        {
            "id": POWER_SOCKET_DEVICE_ID,
            "type": "POWER_SOCKET",
            "attributes": {
                "activity": {"value": "OFF"},
                "state": {"value": "OK"},
                "duration": {"value": 0},
                "lastErrorCode": {"value": "NO_MESSAGE"},
            },
            "relationships": {"device": {"data": {"id": POWER_SOCKET_DEVICE_ID, "type": "DEVICE"}}},
        },
    ],
}

# Robotic Mower (SILENO)
MOWER_LOCATION_RESPONSE = {
    "data": {
        "id": LOCATION_ID,
        "type": "LOCATION",
        "attributes": {"name": {"value": LOCATION_NAME}},
        "relationships": {
            "devices": {"data": [{"id": MOWER_DEVICE_ID, "type": "DEVICE"}]}
        },
    },
    "included": [
        {
            "id": MOWER_DEVICE_ID,
            "type": "DEVICE",
            "relationships": {
                "location": {"data": {"id": LOCATION_ID, "type": "LOCATION"}},
                "services": {
                    "data": [
                        {"id": MOWER_DEVICE_ID, "type": "MOWER"},
                        {"id": MOWER_DEVICE_ID, "type": "COMMON"},
                    ]
                },
            },
        },
        {
            "id": MOWER_DEVICE_ID,
            "type": "COMMON",
            "attributes": {
                "name": {"value": "SILENO"},
                "serial": {"value": "MW001"},
                "modelType": {"value": "GARDENA smart Mower"},
                "batteryLevel": {"value": 90},
                "batteryState": {"value": "OK"},
                "rfLinkLevel": {"value": 80},
                "rfLinkState": {"value": "ONLINE"},
            },
            "relationships": {"device": {"data": {"id": MOWER_DEVICE_ID, "type": "DEVICE"}}},
        },
        {
            "id": MOWER_DEVICE_ID,
            "type": "MOWER",
            "attributes": {
                "activity": {"value": "PARKED_PARK_SELECTED"},
                "state": {"value": "OK"},
                "lastErrorCode": {"value": "NO_MESSAGE"},
                "operatingHours": {"value": 123},
            },
            "relationships": {"device": {"data": {"id": MOWER_DEVICE_ID, "type": "DEVICE"}}},
        },
    ],
}

# Minimal response where services appear before the DEVICE entry (tests alternate parse path)
SERVICE_BEFORE_DEVICE_RESPONSE = {
    "data": {
        "id": LOCATION_ID,
        "type": "LOCATION",
        "attributes": {"name": {"value": LOCATION_NAME}},
        "relationships": {
            "devices": {"data": [{"id": SENSOR_DEVICE_ID, "type": "DEVICE"}]}
        },
    },
    "included": [
        # SENSOR and COMMON appear BEFORE the DEVICE entry
        {
            "id": SENSOR_DEVICE_ID,
            "type": "COMMON",
            "attributes": {
                "name": {"value": "Early Sensor"},
                "serial": {"value": "SN999"},
                "modelType": {"value": "Test"},
                "rfLinkState": {"value": "ONLINE"},
            },
            "relationships": {"device": {"data": {"id": SENSOR_DEVICE_ID, "type": "DEVICE"}}},
        },
        {
            "id": SENSOR_DEVICE_ID,
            "type": "DEVICE",
            "relationships": {
                "location": {"data": {"id": LOCATION_ID, "type": "LOCATION"}},
                "services": {"data": []},
            },
        },
    ],
}

WEBSOCKET_URL_RESPONSE = {
    "data": {
        "type": "WEBSOCKET",
        "attributes": {"url": "wss://ws.smart.gardena.dev/v1/test-ws-url"},
    }
}
