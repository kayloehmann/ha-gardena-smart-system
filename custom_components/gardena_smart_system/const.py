"""Constants for the Gardena Smart System integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "gardena_smart_system"

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_LOCATION_ID = "location_id"
CONF_API_TYPE = "api_type"

API_TYPE_GARDENA = "gardena"
API_TYPE_AUTOMOWER = "automower"

# ── Gardena polling intervals ──────────────────────────────────────
# The Husqvarna Gardena API allows ~3 000 requests/month (~1 every 15 min).
# 30 min keeps us well within budget even without WebSocket.
SCAN_INTERVAL = timedelta(minutes=30)
SCAN_INTERVAL_WS_CONNECTED = timedelta(hours=6)
RATE_LIMIT_COOLDOWN = timedelta(hours=1)

# ── Automower polling intervals ───────────────────────────────────
# The Automower API allows ~10 000 requests/month (~330/day).
# 15 min fallback, 6h with WS, 1h on rate limit.
AUTOMOWER_SCAN_INTERVAL = timedelta(minutes=15)
AUTOMOWER_SCAN_INTERVAL_WS_CONNECTED = timedelta(hours=6)
AUTOMOWER_RATE_LIMIT_COOLDOWN = timedelta(hours=1)

# Minimum seconds between consecutive API commands (mower/valve/power socket)
# to avoid burning through the API quota with rapid-fire automations.
MIN_COMMAND_INTERVAL_SECONDS = 5

# ── Options flow defaults ─────────────────────────────────────────
OPT_DEFAULT_WATERING_MINUTES = "default_watering_minutes"
OPT_DEFAULT_SOCKET_MINUTES = "default_socket_minutes"
OPT_POLL_INTERVAL_MINUTES = "poll_interval_minutes"
DEFAULT_WATERING_MINUTES = 60
DEFAULT_SOCKET_MINUTES = 60
DEFAULT_POLL_INTERVAL_GARDENA = 30
DEFAULT_POLL_INTERVAL_AUTOMOWER = 15
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 1440

GARDENA_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.VALVE,
    Platform.SWITCH,
    Platform.LAWN_MOWER,
    Platform.EVENT,
]

AUTOMOWER_PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.LAWN_MOWER,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.DEVICE_TRACKER,
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.BUTTON,
]

# Keep PLATFORMS as the union for backward compat during migration
PLATFORMS = list(set(GARDENA_PLATFORMS + AUTOMOWER_PLATFORMS))
