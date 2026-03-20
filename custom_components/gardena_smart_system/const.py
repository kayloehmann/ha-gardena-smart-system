"""Constants for the Gardena Smart System integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "gardena_smart_system"

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_LOCATION_ID = "location_id"

# Polling fallback interval (WebSocket is primary; polling only if WS fails)
SCAN_INTERVAL = timedelta(seconds=60)

# Cooldown interval when the API returns HTTP 429 (rate limited)
RATE_LIMIT_COOLDOWN = timedelta(minutes=5)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.VALVE,
    Platform.SWITCH,
    Platform.LAWN_MOWER,
]
