"""Exceptions for the Gardena Smart System API client."""


class GardenaException(Exception):
    """Base exception for all Gardena API errors."""


class GardenaAuthenticationError(GardenaException):
    """Raised when authentication fails (401) or credentials are invalid."""


class GardenaForbiddenError(GardenaException):
    """Raised when the API key / application is not authorized (403).

    Usually means the application connection has not been configured on the
    Husqvarna developer portal for the user's account.
    """


class GardenaRequestError(GardenaException):
    """Raised when a REST API request fails with a non-retryable error."""

    def __init__(self, status: int, message: str) -> None:
        """Initialize with HTTP status and message."""
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class GardenaConnectionError(GardenaException):
    """Raised when a network-level connection error occurs."""


class GardenaWebSocketError(GardenaException):
    """Raised when the WebSocket connection fails unrecoverably."""


class GardenaWebSocketClosedError(GardenaWebSocketError):
    """Raised when the WebSocket connection is closed by the server."""
