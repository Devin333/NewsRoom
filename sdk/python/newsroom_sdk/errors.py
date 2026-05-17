from __future__ import annotations

from typing import Any


class NewsRoomSDKError(Exception):
    """Base class for SDK-side failures."""


class NewsRoomAPIError(NewsRoomSDKError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
        user_action_required: bool = False,
        request_id: str | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.retryable = retryable
        self.user_action_required = user_action_required
        self.request_id = request_id


class NewsRoomConnectionError(NewsRoomSDKError):
    """Raised when the API cannot be reached."""


class NewsRoomTimeoutError(NewsRoomSDKError):
    """Raised when the API request times out."""


class NewsRoomResponseError(NewsRoomSDKError):
    """Raised when the API response is not a valid NewsRoom envelope."""
