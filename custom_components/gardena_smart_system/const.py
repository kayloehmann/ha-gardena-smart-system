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
# The Husqvarna Gardena API allows ~10 000 requests/month (~333/day).
# With WebSocket connected, polls are just health-checks (device list sync).
# With WebSocket down, 5-min polling matches sensor hardware update rate
# and uses ~86% of budget at worst (full month without WS).
SCAN_INTERVAL = timedelta(minutes=5)
SCAN_INTERVAL_WS_CONNECTED = timedelta(hours=1)
RATE_LIMIT_COOLDOWN = timedelta(hours=1)

# ── Automower polling intervals ───────────────────────────────────
# The Automower API allows ~10 000 requests/month (separate budget).
# Same strategy: aggressive fallback, hourly health-check with WS.
AUTOMOWER_SCAN_INTERVAL = timedelta(minutes=5)
AUTOMOWER_SCAN_INTERVAL_WS_CONNECTED = timedelta(hours=1)
AUTOMOWER_RATE_LIMIT_COOLDOWN = timedelta(hours=1)

# Command throttle: token-bucket model.
# Steady-state: at most one command every MIN_COMMAND_INTERVAL_SECONDS — tokens
# refill at 1 per this interval. Burst: up to COMMAND_BURST_CAPACITY commands
# may be fired back-to-back (e.g. a user opening several irrigation valves in
# quick succession) before the throttle kicks in. This preserves the long-term
# API quota budget while not punishing legitimate bursts.
MIN_COMMAND_INTERVAL_SECONDS = 5
COMMAND_BURST_CAPACITY = 10

# WebSocket watchdog: if no message received for this long, consider the
# connection dead and trigger a reconnect.  The Gardena API sends periodic
# WEBSOCKET_PING messages (~every 2 min), so 5 min without any message is
# a reliable indicator of a stale connection.
WS_WATCHDOG_TIMEOUT_SECONDS = 300
WS_WATCHDOG_CHECK_INTERVAL = timedelta(seconds=60)

# ── API budget tracking ──────────────────────────────────────────
API_BUDGET_MONTHLY = 10_000
STORAGE_VERSION_API_BUDGET = 1
BUDGET_SAVE_DELAY_SECONDS = 60
# Auto-stop safety threshold: once less than this percentage of the monthly
# budget is left, the coordinator stops making polls/WS fetches and rejects
# commands until the calendar month rolls over (or the user creates a fresh
# Husqvarna application). 5 % of 10 000 = 500 requests headroom — enough to
# absorb a normal day's activity without being tripped.
API_BUDGET_STOP_PERCENT = 5.0

# ── Options flow defaults ─────────────────────────────────────────
OPT_DEFAULT_WATERING_MINUTES = "default_watering_minutes"
OPT_DEFAULT_SOCKET_MINUTES = "default_socket_minutes"
OPT_POLL_INTERVAL_MINUTES = "poll_interval_minutes"
DEFAULT_WATERING_MINUTES = 60
DEFAULT_SOCKET_MINUTES = 60

# ── MQTT bridge options ──────────────────────────────────────────
OPT_MQTT_ENABLE = "mqtt_enable"
OPT_MQTT_TOPIC_PREFIX = "mqtt_topic_prefix"
OPT_MQTT_PUBLISH_STATES = "mqtt_publish_states"
OPT_MQTT_SUBSCRIBE_COMMANDS = "mqtt_subscribe_commands"
DEFAULT_MQTT_TOPIC_PREFIX = "gardena"
DEFAULT_POLL_INTERVAL_GARDENA = 5
DEFAULT_POLL_INTERVAL_AUTOMOWER = 5
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
    Platform.SELECT,
    Platform.NUMBER,
    Platform.DEVICE_TRACKER,
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.BUTTON,
]

# Keep PLATFORMS as the union for backward compat during migration
PLATFORMS = list(set(GARDENA_PLATFORMS + AUTOMOWER_PLATFORMS))
