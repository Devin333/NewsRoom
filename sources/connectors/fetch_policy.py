from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Callable, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from domain.sources import SourceDefinition, SourceError


Now = Callable[[], datetime]
T = TypeVar("T")
DEFAULT_RETRY_ON_STATUS_CODES = (429, 500, 502, 503, 504)


class UnsupportedContentTypeError(ValueError):
    def __init__(self, content_type: str, supported_content_types: tuple[str, ...]) -> None:
        self.content_type = content_type
        self.supported_content_types = supported_content_types
        supported = ", ".join(supported_content_types)
        super().__init__(f"unsupported content type: {content_type}; supported: {supported}")


@dataclass(frozen=True)
class SourceFetchPolicy:
    timeout_seconds: float = 15.0
    max_bytes: int = 1_000_000
    user_agent: str = "NewsRoom/0.1"
    rate_limit_per_domain_per_minute: int | None = None
    retry_times: int = 2
    retry_on_status_codes: tuple[int, ...] = DEFAULT_RETRY_ON_STATUS_CODES

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
        if self.retry_times < 0:
            raise ValueError("retry_times must be non-negative")
        retry_on_status_codes = tuple(int(code) for code in self.retry_on_status_codes)
        for status_code in retry_on_status_codes:
            if status_code < 100 or status_code > 599:
                raise ValueError("retry_on_status_codes must contain valid HTTP status codes")
        object.__setattr__(self, "retry_on_status_codes", retry_on_status_codes)


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


def run_with_fetch_retries(operation: Callable[[], T], policy: SourceFetchPolicy) -> T:
    attempts = 0
    while True:
        attempts += 1
        try:
            return operation()
        except Exception as exc:
            _set_attempts(exc, attempts)
            if attempts > policy.retry_times or not is_retryable_fetch_exception(exc, policy):
                raise


def is_retryable_fetch_exception(exc: Exception, policy: SourceFetchPolicy) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in policy.retry_on_status_codes
    if _is_timeout_exception(exc):
        return True
    if isinstance(exc, URLError):
        return True
    if isinstance(exc, ValueError):
        return False
    return True


def fetch_attempts(exc: Exception) -> int | None:
    attempts = getattr(exc, "source_fetch_attempts", None)
    return attempts if isinstance(attempts, int) else None


def ensure_supported_content_type(
    content_type: str | None,
    supported_content_types: tuple[str, ...],
) -> None:
    if not content_type:
        return
    normalized = content_type.split(";", 1)[0].strip().casefold()
    supported = tuple(content_type.casefold() for content_type in supported_content_types)
    if normalized not in supported:
        raise UnsupportedContentTypeError(normalized, supported)


def _set_attempts(exc: Exception, attempts: int) -> None:
    try:
        setattr(exc, "source_fetch_attempts", attempts)
    except Exception:
        pass


def _is_timeout_exception(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            return True
        return "timed out" in str(reason).casefold() or "timeout" in str(reason).casefold()
    return False


def _domain_from_url(url: str) -> str:
    parsed = urlsplit(url)
    return (parsed.hostname or parsed.netloc or url).casefold()
