from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class SourceFetchContext:
    run_id: str | None = None
    profile: str | None = None
    topic: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DailySourceConnector(Protocol):
    def fetch(self, *args: Any, **kwargs: Any) -> Any:
        ...


class DailyFeedSourceConnector(DailySourceConnector, Protocol):
    def parse(self, *args: Any, **kwargs: Any) -> Any:
        ...


class DailyHtmlSourceConnector(DailySourceConnector, Protocol):
    pass


class DailyManualSourceConnector(DailySourceConnector, Protocol):
    pass


class DailyArxivSourceConnector(DailySourceConnector, Protocol):
    pass


class DailyGithubSourceConnector(DailySourceConnector, Protocol):
    pass


class DailyHackerNewsSourceConnector(DailySourceConnector, Protocol):
    pass


class DailyRedditSourceConnector(DailySourceConnector, Protocol):
    pass


class DailyLobstersSourceConnector(DailySourceConnector, Protocol):
    pass


class DailyStackOverflowSourceConnector(DailySourceConnector, Protocol):
    pass


class DailyDevToSourceConnector(DailySourceConnector, Protocol):
    pass


class DailyMediumSourceConnector(DailySourceConnector, Protocol):
    pass


class DailySourceRateLimiter(Protocol):
    def reserve(self, url: str, *, limit_per_minute: int | None) -> Any:
        ...


__all__ = [
    "DailyArxivSourceConnector",
    "DailyDevToSourceConnector",
    "DailyFeedSourceConnector",
    "DailyGithubSourceConnector",
    "DailyHackerNewsSourceConnector",
    "DailyHtmlSourceConnector",
    "DailyLobstersSourceConnector",
    "DailyManualSourceConnector",
    "DailyMediumSourceConnector",
    "DailyRedditSourceConnector",
    "DailySourceConnector",
    "DailySourceRateLimiter",
    "DailyStackOverflowSourceConnector",
    "SourceFetchContext",
]
