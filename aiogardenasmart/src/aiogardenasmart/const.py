"""Constants for the Gardena Smart System API client."""

AUTH_TOKEN_URL = "https://api.authentication.husqvarnagroup.dev/v1/oauth2/token"
AUTH_REVOKE_URL = "https://api.authentication.husqvarnagroup.dev/v1/oauth2/revoke"

API_BASE_URL = "https://api.smart.gardena.dev/v2"

# Token refresh buffer: refresh token this many seconds before actual expiry
TOKEN_REFRESH_BUFFER_SECONDS = 300

WEBSOCKET_PING_INTERVAL = 30
WEBSOCKET_PING_TIMEOUT = 10
WEBSOCKET_MAX_RECONNECT_ATTEMPTS = 10
WEBSOCKET_RECONNECT_BASE_DELAY = 5

REQUEST_TIMEOUT = 10

# JSON:API content type required by Gardena API
CONTENT_TYPE_JSON_API = "application/vnd.api+json"
AUTHORIZATION_PROVIDER = "husqvarna"


class ServiceType:
    """Gardena service type strings as returned by the API."""

    COMMON = "COMMON"
    MOWER = "MOWER"
    VALVE = "VALVE"
    VALVE_SET = "VALVE_SET"
    SENSOR = "SENSOR"
    POWER_SOCKET = "POWER_SOCKET"


class ControlType:
    """Control type strings used in command payloads."""

    MOWER = "MOWER_CONTROL"
    VALVE = "VALVE_CONTROL"
    POWER_SOCKET = "POWER_SOCKET_CONTROL"


class MowerActivity:
    """Possible MOWER activity values."""

    OK_CUTTING = "OK_CUTTING"
    OK_CUTTING_TIMER_OVERRIDDEN = "OK_CUTTING_TIMER_OVERRIDDEN"
    OK_SEARCHING = "OK_SEARCHING"
    OK_LEAVING = "OK_LEAVING"
    OK_CHARGING = "OK_CHARGING"
    PARKED_TIMER = "PARKED_TIMER"
    PARKED_PARK_SELECTED = "PARKED_PARK_SELECTED"
    PARKED_AUTOTIMER = "PARKED_AUTOTIMER"
    PARKED_FROST = "PARKED_FROST"
    PAUSED = "PAUSED"
    PAUSED_IN_CS = "PAUSED_IN_CS"
    STOPPED_IN_GARDEN = "STOPPED_IN_GARDEN"
    NONE = "NONE"


class ValveActivity:
    """Possible VALVE activity values."""

    CLOSED = "CLOSED"
    MANUAL_WATERING = "MANUAL_WATERING"
    SCHEDULED_WATERING = "SCHEDULED_WATERING"


class PowerSocketActivity:
    """Possible POWER_SOCKET activity values."""

    OFF = "OFF"
    FOREVER_ON = "FOREVER_ON"
    TIME_LIMITED_ON = "TIME_LIMITED_ON"
    SCHEDULED_ON = "SCHEDULED_ON"


class ServiceState:
    """Generic state values shared across service types."""

    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    UNAVAILABLE = "UNAVAILABLE"


class BatteryState:
    """COMMON batteryState values."""

    OK = "OK"
    LOW = "LOW"
    REPLACE_NOW = "REPLACE_NOW"
    OUT_OF_OPERATION = "OUT_OF_OPERATION"
    CHARGING = "CHARGING"
    NO_BATTERY = "NO_BATTERY"
    UNKNOWN = "UNKNOWN"


class RfLinkState:
    """COMMON rfLinkState values."""

    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
