"""Constants for the Gardena Smart System integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "gardena_smart_system"

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_LOCATION_ID = "location_id"

# Polling fallback interval (WebSocket is primary; polling only if WS fails).
# The Husqvarna API allows ~3 000 requests/month (~1 every 15 min).
# 30 min keeps us well within budget even without WebSocket.
SCAN_INTERVAL = timedelta(minutes=30)

# When the WebSocket is connected and delivering real-time updates, polling
# serves only as a rare health-check. Use a long interval to conserve quota.
SCAN_INTERVAL_WS_CONNECTED = timedelta(hours=6)

# Cooldown interval when the API returns HTTP 429 (rate limited)
RATE_LIMIT_COOLDOWN = timedelta(hours=1)

# Minimum seconds between consecutive API commands (mower/valve/power socket)
# to avoid burning through the API quota with rapid-fire automations.
MIN_COMMAND_INTERVAL_SECONDS = 5

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.VALVE,
    Platform.SWITCH,
    Platform.LAWN_MOWER,
]
