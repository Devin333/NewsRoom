from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone as _tz
from math import ceil
from typing import Protocol
from urllib.parse import urlsplit

from business.foundation.models.source import (
    RawSourceItem,
    SourceDefinition,
    SourceError,
    SourceFetchPolicy,
)
from business.layers.signal.source_processing.error_metadata import (
    SourceErrorMetadataInput,
    source_error_metadata,
)


UTC = _tz.utc
FetchText = Callable[[str], str]


@dataclass(frozen=True)
class SourceTextFetchResult:
    content: str
    status_code: int | None = None
    content_type: str | None = None


@dataclass(frozen=True)
class SourceRateLimitDecision:
    allowed: bool
    domain: str
    limit_per_minute: int | None
    window_seconds: int = 60
    retry_after_seconds: int | None = None


class SourceDomainRateLimiter:
    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))
        self._requests: dict[str, deque[datetime]] = defaultdict(deque)

    def reserve(self, url: str, *, limit_per_minute: int | None) -> SourceRateLimitDecision:
        domain = _domain_from_url(url)
        if limit_per_minute is None:
            return SourceRateLimitDecision(
                allowed=True,
                domain=domain,
                limit_per_minute=None,
            )
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
            return SourceRateLimitDecision(
                allowed=False,
                domain=domain,
                limit_per_minute=limit_per_minute,
                retry_after_seconds=retry_after,
            )

        bucket.append(now)
        return SourceRateLimitDecision(
            allowed=True,
            domain=domain,
            limit_per_minute=limit_per_minute,
        )

    def _current_time(self) -> datetime:
        current = self._now()
        if current.tzinfo is None:
            return current.replace(tzinfo=UTC)
        return current.astimezone(UTC)


class SourceToolRuntime(Protocol):
    def fetch_text(self, url: str, policy: SourceFetchPolicy) -> SourceTextFetchResult:
        ...

    def parse_feed(
        self,
        source: SourceDefinition,
        content: str,
        *,
        limit: int | None = None,
    ) -> list[RawSourceItem]:
        ...

    def parse_html(
        self,
        source: SourceDefinition,
        content: str,
        *,
        limit: int | None = None,
    ) -> list[RawSourceItem]:
        ...

    def fetch_manual(
        self,
        source: SourceDefinition,
        *,
        records: Sequence[dict[str, object]],
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        ...

    def fetch_official_blog(
        self,
        source: SourceDefinition,
        *,
        policy: SourceFetchPolicy,
        limit: int | None = None,
    ) -> tuple[list[RawSourceItem], list[SourceError]]:
        ...


def effective_source_fetch_policy(
    policy: SourceFetchPolicy,
    source: SourceDefinition,
) -> SourceFetchPolicy:
    return replace(
        policy,
        respect_robots=policy.respect_robots and source.respect_robots,
        user_agent=source.user_agent or policy.user_agent,
    )


def source_rate_limited_error(
    source: SourceDefinition,
    decision: SourceRateLimitDecision,
    *,
    url: str,
) -> SourceError:
    return SourceError(
        source_id=source.source_id,
        source_name=source.name,
        error_type="rate_limited",
        error_message=f"source fetch rate limit reached for domain: {decision.domain}",
        url=url,
        retryable=True,
        metadata=source_error_metadata(
            SourceErrorMetadataInput(
                phase="fetch",
                retryable=True,
                source_health_affecting=False,
                workflow_blocking=False,
                extra={
                    "domain": decision.domain,
                    "limit_per_minute": decision.limit_per_minute,
                    "window_seconds": decision.window_seconds,
                    "retry_after_seconds": decision.retry_after_seconds,
                },
            )
        ),
    )


def run_fetch_with_retries(operation: Callable[[], SourceTextFetchResult], policy: SourceFetchPolicy) -> SourceTextFetchResult:
    attempts = 0
    while True:
        attempts += 1
        try:
            return operation()
        except Exception as exc:
            _set_attempts(exc, attempts)
            if attempts > policy.retry_times or not _is_retryable_fetch_exception(exc):
                raise


def source_fetch_policy_without_rate_limit(policy: SourceFetchPolicy) -> SourceFetchPolicy:
    return replace(policy, rate_limit_per_domain_per_minute=None)


def _domain_from_url(url: str) -> str:
    parsed = urlsplit(url)
    return (parsed.hostname or "").casefold()


def _set_attempts(exc: Exception, attempts: int) -> None:
    try:
        setattr(exc, "source_fetch_attempts", attempts)
    except Exception:
        pass


def _is_retryable_fetch_exception(exc: Exception) -> bool:
    if isinstance(exc, ValueError):
        return False
    return True


__all__ = [
    "FetchText",
    "SourceDomainRateLimiter",
    "SourceRateLimitDecision",
    "SourceTextFetchResult",
    "SourceToolRuntime",
    "effective_source_fetch_policy",
    "run_fetch_with_retries",
    "source_fetch_policy_without_rate_limit",
    "source_rate_limited_error",
]
