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
# connection logically dead and trigger a reconnect. aiohttp's `heartbeat=30`
# (in `aiogardenasmart.websocket`) already detects TCP-level connection
# death within ~60 s via WS protocol PING/PONG frames, so this watchdog is
# a SECOND-LEVEL safety net for "TCP alive but app silent" — i.e. cases
# where the Gardena server has logically forgotten about us.
#
# Previously set to 300 s under the assumption that the API sends app-level
# `WEBSOCKET_PING` messages every ~2 min. That assumption holds for chatty
# accounts but fails for users whose devices stay quiet (no state changes,
# no app-level pings) — see issue #18: a perfectly healthy WS gets killed
# every 6 min, and the immediate reconnect frequently triggers HTTP 410 on
# the new signed URL because the server hasn't released the prior session.
# That single-handedly burned ~240 reconnects/day = ~70 % of the monthly
# REST budget on healthy connections.
#
# 30 min is well past any realistic app-level idle window (Husqvarna's
# product behaviour for a low-activity garden), keeps the safety net for
# truly stuck WS sessions, and aligns with the WS-connected hourly health-
# check poll which catches "WS dead but TCP alive" on the next REST tick.
WS_WATCHDOG_TIMEOUT_SECONDS = 1800
WS_WATCHDOG_CHECK_INTERVAL = timedelta(seconds=60)

# WebSocket handshake kill-switch: after this many consecutive 4xx handshake
# rejections (403 / 410 / 429) the WS subsystem is suspended for
# WS_KILL_SWITCH_COOLDOWN. This protects the REST rate-limit budget when the
# server is persistently rejecting signed WS URLs — typically a symptom of an
# account-level block no amount of client retry logic can recover from.
# Reset only when an actual device update is received (confirming the stream
# is healthy), not on the synchronous ws_connect() returning.
WS_HANDSHAKE_DENIAL_THRESHOLD = 5
WS_KILL_SWITCH_COOLDOWN = timedelta(hours=1)
WS_HANDSHAKE_DENIAL_STATUSES = frozenset({403, 410, 429})

# Rate-limit reset: require this many consecutive successful polls before
# clearing the _rate_limit_hits counter. Without this, a single successful
# response resets the backoff ladder — so a persistent rate-limit scenario
# produces a saw-tooth pattern of #1 → #2 → … → #6 → reset → #1 → … rather
# than holding at the maximum backoff.
RATE_LIMIT_RESET_SUCCESS_THRESHOLD = 3

# WebSocket repair-issue threshold: only surface a HA repair notification once
# the WS has failed this many times in a row. A single transient drop (which
# auto-reconnects in seconds) would otherwise create visible noise for users
# — see issue #17. This threshold aligns with the first cooldown step in
# `_WS_COOLDOWN_SCHEDULE`, so the issue appears together with the first user-
# visible slowdown rather than on every micro-blip.
WS_REPAIR_ISSUE_THRESHOLD = 3

# ── API budget tracking ──────────────────────────────────────────
API_BUDGET_MONTHLY = 10_000
STORAGE_VERSION_API_BUDGET = 1
BUDGET_SAVE_DELAY_SECONDS = 60

# ── Rate-limit state persistence ─────────────────────────────────
# `_rate_limit_hits`, `_ws_handshake_denials`, and `_ws_kill_switch_until` were
# in-memory only — they were lost every time the coordinator was rebuilt
# (config-entry setup retry on UpdateFailed, HA restart). That made the kill-
# switch effectively unreachable while the integration was stuck in a setup-
# retry loop, because each retry started the counters from zero. Persisting
# the state via Store so it survives both restarts and setup retries.
STORAGE_VERSION_RATE_LIMIT_STATE = 1
RATE_LIMIT_STATE_SAVE_DELAY_SECONDS = 5

# ── Persistent application-block detector ────────────────────────
# When the rate-limit ladder keeps firing AND no successful poll has happened
# for a long time, the Husqvarna Application is almost certainly server-side
# blocked. Surface the existing husqvarna_application_blocked Repair issue so
# the user knows to rotate the Application — there is nothing client-side
# retry logic can do at that point.
APPLICATION_BLOCKED_RATE_LIMIT_THRESHOLD = 10
APPLICATION_BLOCKED_NO_SUCCESS_HOURS = 24
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
