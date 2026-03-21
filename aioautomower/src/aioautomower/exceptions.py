"""Exceptions for the Automower Connect API client."""


class AutomowerException(Exception):
    """Base exception for all Automower API errors."""


class AutomowerAuthenticationError(AutomowerException):
    """Raised when authentication fails (401) or credentials are invalid."""


class AutomowerForbiddenError(AutomowerException):
    """Raised when the API key is not authorized for the Automower Connect API (403).

    Usually means the Automower Connect API has not been connected to the
    application on the Husqvarna Developer Portal.
    """


class AutomowerRateLimitError(AutomowerException):
    """Raised when the API returns HTTP 429 (rate limited)."""


class AutomowerRequestError(AutomowerException):
    """Raised when a REST API request fails with a non-retryable error."""

    def __init__(self, status: int, message: str) -> None:
        """Initialize with HTTP status and message."""
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class AutomowerConnectionError(AutomowerException):
    """Raised when a network-level connection error occurs."""


class AutomowerWebSocketError(AutomowerException):
    """Raised when the WebSocket connection fails unrecoverably."""
