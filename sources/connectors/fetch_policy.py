from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Callable
from urllib.parse import urlsplit

from domain.sources import SourceDefinition, SourceError


Now = Callable[[], datetime]


@dataclass(frozen=True)
class SourceFetchPolicy:
    timeout_seconds: float = 15.0
    max_bytes: int = 1_000_000
    user_agent: str = "NewsRoom/0.1"
    rate_limit_per_domain_per_minute: int | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")
        if not self.user_agent:
            raise ValueError("user_agent is required")
        if (
            self.rate_limit_per_domain_per_minute is not None
            and self.rate_limit_per_domain_per_minute < 1
        ):
            raise ValueError("rate_limit_per_domain_per_minute must be at least 1")


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    domain: str
    limit_per_minute: int | None
    window_seconds: int = 60
    retry_after_seconds: int | None = None


class DomainRateLimiter:
    def __init__(self, *, now: Now | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._requests: dict[str, deque[datetime]] = defaultdict(deque)

    def reserve(self, url: str, *, limit_per_minute: int | None) -> RateLimitDecision:
        domain = _domain_from_url(url)
        if limit_per_minute is None:
            return RateLimitDecision(allowed=True, domain=domain, limit_per_minute=None)
        if limit_per_minute < 1:
            raise ValueError("limit_per_minute must be at least 1")

        now = self._current_time()
        window_start = now - timedelta(seconds=60)
        bucket = self._requests[domain]
        while bucket and bucket[0] <= window_start:
            bucket.popleft()

        if len(bucket) >= limit_per_minute:
            retry_at = bucket[0] + timedelta(seconds=60)
            retry_after = max(1, ceil((retry_at - now).total_seconds()))
            return RateLimitDecision(
                allowed=False,
                domain=domain,
                limit_per_minute=limit_per_minute,
                retry_after_seconds=retry_after,
            )

        bucket.append(now)
        return RateLimitDecision(allowed=True, domain=domain, limit_per_minute=limit_per_minute)

    def _current_time(self) -> datetime:
        current = self._now()
        if current.tzinfo is None:
            return current.replace(tzinfo=UTC)
        return current.astimezone(UTC)


def rate_limited_source_error(
    source: SourceDefinition,
    decision: RateLimitDecision,
    *,
    url: str,
) -> SourceError:
    return SourceError(
        source_id=source.source_id,
        error_type="rate_limited",
        error_message=f"source fetch rate limit reached for domain: {decision.domain}",
        url=url,
        metadata={
            "phase": "fetch",
            "retryable": True,
            "source_health_affecting": False,
            "domain": decision.domain,
            "limit_per_minute": decision.limit_per_minute,
            "window_seconds": decision.window_seconds,
            "retry_after_seconds": decision.retry_after_seconds,
        },
    )


def _domain_from_url(url: str) -> str:
    parsed = urlsplit(url)
    return (parsed.hostname or parsed.netloc or url).casefold()
