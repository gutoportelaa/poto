"""GovChat SDK exceptions."""


class GovChatError(Exception):
    """Base exception for GovChat SDK."""

    pass


class GovChatApiError(GovChatError):
    """API returned an error response."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"GovChat API error ({status_code}): {message}")


class GovChatConnectionError(GovChatError):
    """Network/connection error."""

    pass


class GovChatTimeoutError(GovChatError):
    """Request timeout."""

    pass


class GovChatConfigError(GovChatError):
    """Configuration error (missing API token, account ID, etc.)."""

    pass
