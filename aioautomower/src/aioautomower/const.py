"""Constants for the Husqvarna Automower Connect API v1 client."""

API_BASE_URL = "https://api.amc.husqvarna.dev/v1"

AUTHORIZATION_PROVIDER = "husqvarna"

REQUEST_TIMEOUT = 10

WEBSOCKET_PING_INTERVAL = 30
WEBSOCKET_MAX_RECONNECT_ATTEMPTS = 5
WEBSOCKET_RECONNECT_BASE_DELAY = 30


class MowerMode:
    """Automower operating modes."""

    MAIN_AREA = "MAIN_AREA"
    SECONDARY_AREA = "SECONDARY_AREA"
    HOME = "HOME"
    DEMO = "DEMO"
    UNKNOWN = "UNKNOWN"


class MowerActivity:
    """Automower activity states."""

    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    MOWING = "MOWING"
    GOING_HOME = "GOING_HOME"
    CHARGING = "CHARGING"
    LEAVING = "LEAVING"
    PARKED_IN_CS = "PARKED_IN_CS"
    STOPPED_IN_GARDEN = "STOPPED_IN_GARDEN"


class MowerState:
    """Automower device states."""

    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PAUSED = "PAUSED"
    IN_OPERATION = "IN_OPERATION"
    WAIT_UPDATING = "WAIT_UPDATING"
    WAIT_POWER_UP = "WAIT_POWER_UP"
    RESTRICTED = "RESTRICTED"
    OFF = "OFF"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    FATAL_ERROR = "FATAL_ERROR"
    ERROR_AT_POWER_UP = "ERROR_AT_POWER_UP"


class RestrictedReason:
    """Reasons why the mower is restricted from mowing."""

    NONE = "NONE"
    WEEK_SCHEDULE = "WEEK_SCHEDULE"
    PARK_OVERRIDE = "PARK_OVERRIDE"
    SENSOR = "SENSOR"
    DAILY_LIMIT = "DAILY_LIMIT"
    FOTA = "FOTA"
    FROST = "FROST"
    ALL_WORK_AREAS_COMPLETED = "ALL_WORK_AREAS_COMPLETED"
    EXTERNAL = "EXTERNAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class HeadlightMode:
    """Headlight operating modes."""

    ALWAYS_ON = "ALWAYS_ON"
    ALWAYS_OFF = "ALWAYS_OFF"
    EVENING_ONLY = "EVENING_ONLY"
    EVENING_AND_NIGHT = "EVENING_AND_NIGHT"


class ActionType:
    """Command action types for POST /mowers/{id}/actions."""

    START = "Start"
    PAUSE = "Pause"
    PARK_UNTIL_NEXT_SCHEDULE = "ParkUntilNextSchedule"
    PARK_UNTIL_FURTHER_NOTICE = "ParkUntilFurtherNotice"
    RESUME_SCHEDULE = "ResumeSchedule"


class OverrideAction:
    """Planner override action values."""

    NOT_ACTIVE = "NOT_ACTIVE"
    FORCE_PARK = "FORCE_PARK"
    FORCE_MOW = "FORCE_MOW"
