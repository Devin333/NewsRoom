"""Synchronous Python SDK for the NewsRoom HTTP API."""

from newsroom_sdk.client import NewsRoomClient
from newsroom_sdk.errors import (
    NewsRoomAPIError,
    NewsRoomConnectionError,
    NewsRoomSDKError,
    NewsRoomTimeoutError,
)

__all__ = [
    "NewsRoomAPIError",
    "NewsRoomClient",
    "NewsRoomConnectionError",
    "NewsRoomSDKError",
    "NewsRoomTimeoutError",
]
