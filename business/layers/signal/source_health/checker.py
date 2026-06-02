from __future__ import annotations

from collections.abc import Callable
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone as _tz
from math import ceil
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from business.foundation.models.source import (
    SourceDefinition,
    SourceError,
    SourceFetchPolicy,
    SourceHealth,
    SourceHealthStatus,
    SourcePipelineEvent,
    SourceType,
)
from business.foundation.registry.source_registry import SourceRegistry
from business.layers.signal.source_health.manager import BasicSourceHealthManager


ProbeFetcher = Callable[[SourceDefinition, SourceFetchPolicy], "ProbeObservation"]
UTC = _tz.utc


@dataclass(frozen=True)
class ProbeObservation:
    status_code: int | None
    content_type: str | None
    content_bytes: int
    final_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status_code": self.status_code,
            "content_type": self.content_type,
            "content_bytes": self.content_bytes,
            "final_url": self.final_url,
        }


@dataclass(frozen=True)
class SourceHealthCheckEntry:
    source_id: str
    source_name: str
    url: str
    status: str
    ok: bool
    skipped: bool = False
    skip_reason: str | None = None
    latency_ms: float | None = None
    observation: ProbeObservation | None = None
    health: SourceHealth | None = None
    error: SourceError | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "url": self.url,
            "status": self.status,
            "ok": self.ok,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "latency_ms": self.latency_ms,
            "observation": self.observation.to_dict() if self.observation else None,
            "health": self.health.to_dict() if self.health else None,
            "error": self.error.to_dict() if self.error else None,
        }


@dataclass(frozen=True)
class SourceHealthCheckResult:
    checked_count: int
    succeeded_count: int
    failed_count: int
    skipped_count: int
    entries: list[SourceHealthCheckEntry] = field(default_factory=list)
    events: list[SourcePipelineEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_count": self.checked_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "entries": [entry.to_dict() for entry in self.entries],
            "events": [event.to_dict() for event in self.events],
        }


class SourceHealthChecker:
    def __init__(
        self,
        source_registry: SourceRegistry,
        health_manager: BasicSourceHealthManager,
        *,
        fetch_policy: SourceFetchPolicy | None = None,
        probe_fetcher: ProbeFetcher | None = None,
        rate_limiter: Any | None = None,
    ) -> None:
        self.source_registry = source_registry
        self.health_manager = health_manager
        self.fetch_policy = _source_fetch_policy(fetch_policy, default=SourceFetchPolicy(max_bytes=128_000))
        self.probe_fetcher = probe_fetcher or _missing_probe_fetcher
        self.rate_limiter = rate_limiter or SourceDomainRateLimiter()

    def run(
        self,
        *,
        source_id: str | None = None,
        enabled_only: bool = True,
        limit: int | None = None,
        force: bool = False,
    ) -> SourceHealthCheckResult:
        sources = self._selected_sources(source_id=source_id, enabled_only=enabled_only, limit=limit)
        entries: list[SourceHealthCheckEntry] = []
        events: list[SourcePipelineEvent] = []
        for source in sources:
            entry, source_events = self._check_source(source, force=force)
            entries.append(entry)
            events.extend(source_events)
        return SourceHealthCheckResult(
            checked_count=len(entries),
            succeeded_count=sum(1 for entry in entries if entry.ok and not entry.skipped),
            failed_count=sum(1 for entry in entries if not entry.ok and not entry.skipped),
            skipped_count=sum(1 for entry in entries if entry.skipped),
            entries=entries,
            events=events,
        )

    def _selected_sources(
        self,
        *,
        source_id: str | None,
        enabled_only: bool,
        limit: int | None,
    ) -> list[SourceDefinition]:
        if source_id:
            source = self.source_registry.get(source_id)
            if enabled_only and not source.enabled:
                return []
            return [source]
        sources = self.source_registry.list_sources(enabled_only=enabled_only)
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be greater than zero")
            sources = sources[:limit]
        return sources

    def _check_source(
        self,
        source: SourceDefinition,
        *,
        force: bool,
    ) -> tuple[SourceHealthCheckEntry, list[SourcePipelineEvent]]:
        events: list[SourcePipelineEvent] = []
        if not source.enabled:
            health = self.health_manager.record_disabled(
                source.source_id,
                reason="source disabled by configuration",
                source_name=source.name,
                url=source.url,
            )
            return (
                _entry(source, status=health.status.value, ok=False, skipped=True, skip_reason="disabled", health=health),
                [_event("source_health_updated", source, status=health.status.value)],
            )

        if self.health_manager.should_skip(source.source_id) and not force:
            health = self.health_manager.get(source.source_id, source_name=source.name, url=source.url)
            return (
                _entry(source, status=health.status.value, ok=False, skipped=True, skip_reason="cooldown", health=health),
                [
                    _event(
                        "source_fetch_skipped",
                        source,
                        reason="cooldown",
                        cooldown_until=_dt(health.cooldown_until),
                    )
                ],
            )

        policy = effective_fetch_policy(self.fetch_policy, source)
        rate_limit_error = _rate_limit_error(source, policy, self.rate_limiter)
        if rate_limit_error is not None:
            health = self.health_manager.get(
                source.source_id,
                source_name=source.name,
                url=source.url,
            )
            return (
                _entry(
                    source,
                    status=health.status.value,
                    ok=False,
                    skipped=True,
                    skip_reason="rate_limited",
                    health=health,
                    error=rate_limit_error,
                ),
                [
                    _event(
                        "source_fetch_skipped",
                        source,
                        reason="rate_limited",
                        domain=rate_limit_error.metadata.get("domain"),
                        retry_after_seconds=rate_limit_error.metadata.get(
                            "retry_after_seconds"
                        ),
                    ),
                    _event(
                        "source_health_updated",
                        source,
                        status=health.status.value,
                        consecutive_failures=health.consecutive_failures,
                    ),
                ],
            )

        events.append(_event("source_probe_started", source, force=force))
        latency_start = perf_counter()
        try:
            observation = self.probe_fetcher(source, policy)
        except Exception as exc:
            latency_ms = _elapsed_ms(latency_start)
            error = _exception_source_error(source, exc)
            health = self.health_manager.record_failure(
                source.source_id,
                error,
                latency_ms=latency_ms,
                source_name=source.name,
                url=source.url,
            )
            events.append(
                _event(
                    "source_probe_failed",
                    source,
                    error_type=error.error_type,
                    latency_ms=latency_ms,
                )
            )
            if health.status == SourceHealthStatus.DOWN:
                events.append(
                    _event(
                        "source_cooldown_started",
                        source,
                        cooldown_until=_dt(health.cooldown_until),
                        consecutive_failures=health.consecutive_failures,
                    )
                )
            events.append(
                _event(
                    "source_health_updated",
                    source,
                    status=health.status.value,
                    consecutive_failures=health.consecutive_failures,
                )
            )
            return (
                _entry(
                    source,
                    status=health.status.value,
                    ok=False,
                    latency_ms=latency_ms,
                    health=health,
                    error=error,
                ),
                events,
            )

        latency_ms = _elapsed_ms(latency_start)
        health = self.health_manager.record_success(
            source.source_id,
            latency_ms=latency_ms,
            source_name=source.name,
            url=source.url,
        )
        events.append(
            _event(
                "source_probe_succeeded",
                source,
                latency_ms=latency_ms,
                status_code=observation.status_code,
                content_bytes=observation.content_bytes,
            )
        )
        events.append(
            _event(
                "source_health_updated",
                source,
                status=health.status.value,
                consecutive_failures=health.consecutive_failures,
            )
        )
        return (
            _entry(
                source,
                status=health.status.value,
                ok=True,
                latency_ms=latency_ms,
                observation=observation,
                health=health,
            ),
            events,
        )


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
            return SourceRateLimitDecision(allowed=True, domain=domain, limit_per_minute=None)
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
        return SourceRateLimitDecision(allowed=True, domain=domain, limit_per_minute=limit_per_minute)

    def _current_time(self) -> datetime:
        current = self._now()
        if current.tzinfo is None:
            return current.replace(tzinfo=UTC)
        return current.astimezone(UTC)


def _missing_probe_fetcher(source: SourceDefinition, policy: SourceFetchPolicy) -> ProbeObservation:
    raise RuntimeError("source health probe_fetcher is required")


def _entry(
    source: SourceDefinition,
    *,
    status: str,
    ok: bool,
    skipped: bool = False,
    skip_reason: str | None = None,
    latency_ms: float | None = None,
    observation: ProbeObservation | None = None,
    health: SourceHealth | None = None,
    error: SourceError | None = None,
) -> SourceHealthCheckEntry:
    return SourceHealthCheckEntry(
        source_id=source.source_id,
        source_name=source.name,
        url=source.url,
        status=status,
        ok=ok,
        skipped=skipped,
        skip_reason=skip_reason,
        latency_ms=latency_ms,
        observation=observation,
        health=health,
        error=error,
    )


def _event(event_type: str, source: SourceDefinition, **metadata: Any) -> SourcePipelineEvent:
    return SourcePipelineEvent(
        event_type=event_type,
        source_id=source.source_id,
        metadata={
            "source_name": source.name,
            "source_type": _source_type(source).value,
            "url": source.url,
            **{key: value for key, value in metadata.items() if value is not None},
        },
    )


def _exception_source_error(source: SourceDefinition, exc: Exception) -> SourceError:
    error_type, retryable, health_affecting = _classify_probe_exception(exc)
    metadata: dict[str, Any] = {
        "phase": "probe",
        "retryable": retryable,
        "source_health_affecting": health_affecting,
        "original_exception_type": type(exc).__name__,
    }
    if isinstance(exc, HTTPError):
        metadata["status_code"] = exc.code
    exception_type = type(exc).__name__
    if exception_type == "UnsupportedContentTypeError":
        metadata["content_type"] = getattr(exc, "content_type", None)
        metadata["supported_content_types"] = list(getattr(exc, "supported_content_types", ()) or ())
    if exception_type == "TooManyRedirectsError":
        metadata["redirect_url"] = getattr(exc, "url", None)
        metadata["max_redirects"] = getattr(exc, "max_redirects", None)
    if exception_type == "RobotsDisallowedError":
        metadata["robots_url"] = getattr(exc, "robots_url", None)
        metadata["user_agent"] = getattr(exc, "user_agent", None)
    attempts = getattr(exc, "source_fetch_attempts", None)
    if attempts is not None:
        metadata["attempts"] = attempts
    return SourceError(
        source_id=source.source_id,
        source_name=source.name,
        error_type=error_type,
        error_message=str(exc),
        url=source.url,
        retryable=retryable,
        metadata=metadata,
    )


def _rate_limit_error(
    source: SourceDefinition,
    policy: SourceFetchPolicy,
    rate_limiter: Any,
) -> SourceError | None:
    decision = rate_limiter.reserve(
        source.url,
        limit_per_minute=policy.rate_limit_per_domain_per_minute,
    )
    if decision.allowed:
        return None
    return SourceError(
        source_id=source.source_id,
        source_name=source.name,
        error_type="rate_limited",
        error_message=f"source fetch rate limit reached for domain: {decision.domain}",
        url=source.url,
        retryable=True,
        metadata={
            "phase": "fetch",
            "retryable": True,
            "source_health_affecting": False,
            "domain": decision.domain,
            "limit_per_minute": decision.limit_per_minute,
            "window_seconds": getattr(decision, "window_seconds", 60),
            "retry_after_seconds": decision.retry_after_seconds,
        },
    )


def _source_type(source: SourceDefinition) -> SourceType:
    return SourceType(source.source_type)


def effective_fetch_policy(policy: SourceFetchPolicy, source: SourceDefinition) -> SourceFetchPolicy:
    user_agent = source.user_agent or policy.user_agent
    return replace(
        policy,
        respect_robots=policy.respect_robots and source.respect_robots,
        user_agent=user_agent,
    )


def _classify_probe_exception(exc: Exception) -> tuple[str, bool, bool]:
    exception_type = type(exc).__name__
    if exception_type == "UnsupportedContentTypeError":
        return "unsupported_content_type", False, False
    if exception_type == "TooManyRedirectsError":
        return "too_many_redirects", False, False
    if exception_type == "RobotsDisallowedError":
        return "robots_disallowed", False, False
    if _is_invalid_source_config(exc):
        return "invalid_source_config", False, False
    if isinstance(exc, HTTPError):
        if 400 <= exc.code < 500:
            return "fetch_http_4xx", exc.code in {408, 409, 425, 429}, True
        if exc.code >= 500:
            return "fetch_http_5xx", True, True
        return "fetch_connection_error", True, True
    if _is_timeout_exception(exc):
        return "fetch_timeout", True, True
    if isinstance(exc, ValueError) and "max_bytes" in str(exc):
        return "max_bytes_exceeded", False, False
    return "fetch_connection_error", True, True

def _is_invalid_source_config(exc: Exception) -> bool:
    if not isinstance(exc, ValueError):
        return False
    return "source url" in str(exc).casefold()


def _source_fetch_policy(policy: Any | None, *, default: SourceFetchPolicy) -> SourceFetchPolicy:
    if policy is None:
        return default
    if isinstance(policy, SourceFetchPolicy):
        return policy
    return SourceFetchPolicy(
        timeout_seconds=policy.timeout_seconds,
        max_bytes=policy.max_bytes,
        max_redirects=policy.max_redirects,
        user_agent=policy.user_agent,
        respect_robots=policy.respect_robots,
        rate_limit_per_domain_per_minute=policy.rate_limit_per_domain_per_minute,
        allowed_domains=tuple(getattr(policy, "allowed_domains", ()) or ()),
        retry_times=policy.retry_times,
        retry_on_status_codes=tuple(policy.retry_on_status_codes),
    )


def _is_timeout_exception(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, TimeoutError):
            return True
        return "timed out" in str(reason).casefold() or "timeout" in str(reason).casefold()
    return False


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 3)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _domain_from_url(url: str) -> str:
    parsed = urlsplit(url)
    return (parsed.hostname or parsed.netloc or url).casefold()
