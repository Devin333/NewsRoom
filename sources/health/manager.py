from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from domain.sources import SourceError, SourceHealth, SourceHealthStatus

HEALTH_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class _HealthEvent:
    occurred_at: datetime
    succeeded: bool
    latency_ms: float | None = None


@dataclass(frozen=True)
class _HealthWindowStats:
    success_count_24h: int = 0
    failure_count_24h: int = 0
    avg_latency_ms_24h: float | None = None


class BasicSourceHealthManager:
    def __init__(
        self,
        *,
        failure_threshold: int = 2,
        cooldown_seconds: int = 300,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._health: dict[str, SourceHealth] = {}
        self._events: dict[str, list[_HealthEvent]] = {}

    def get(
        self,
        source_id: str,
        *,
        source_name: str | None = None,
        url: str | None = None,
    ) -> SourceHealth:
        health = self._health.get(source_id, SourceHealth(source_id=source_id))
        health = _with_window_stats(health, self._window_stats(source_id, now=self._now()))
        health = _with_source_context(health, source_name=source_name, url=url)
        if source_name is not None or url is not None:
            self._health[source_id] = health
        return health

    def should_skip(self, source_id: str) -> bool:
        health = self.get(source_id)
        if health.status == SourceHealthStatus.DISABLED:
            return True
        return (
            health.status == SourceHealthStatus.COOLING_DOWN
            and health.cooldown_until is not None
            and health.cooldown_until > self._now()
        )

    def should_fetch(self, source_id: str) -> bool:
        return not self.should_skip(source_id)

    def should_probe(self, source_id: str) -> bool:
        health = self.get(source_id)
        return (
            health.status == SourceHealthStatus.COOLING_DOWN
            and health.cooldown_until is not None
            and health.cooldown_until <= self._now()
        )

    def record_success(
        self,
        source_id: str,
        *,
        latency_ms: float | None = None,
        source_name: str | None = None,
        url: str | None = None,
    ) -> SourceHealth:
        previous = self.get(source_id)
        now = self._now()
        stats = self._record_event(source_id, succeeded=True, latency_ms=latency_ms, now=now)
        health = SourceHealth(
            source_id=source_id,
            source_name=source_name or previous.source_name,
            url=url or previous.url,
            status=SourceHealthStatus.HEALTHY,
            consecutive_failures=0,
            success_count_24h=stats.success_count_24h,
            failure_count_24h=stats.failure_count_24h,
            avg_latency_ms_24h=stats.avg_latency_ms_24h,
            last_success_at=now,
            last_failure_at=previous.last_failure_at,
        )
        self._health[source_id] = health
        return health

    def record_disabled(
        self,
        source_id: str,
        *,
        reason: str | None = None,
        source_name: str | None = None,
        url: str | None = None,
    ) -> SourceHealth:
        previous = self.get(source_id)
        error = SourceError(
            source_id=source_id,
            source_name=source_name or previous.source_name,
            error_type="source_disabled",
            error_message=reason or "source is disabled",
            url=url or previous.url,
            metadata={"retryable": False, "source_health_affecting": False},
        )
        health = SourceHealth(
            source_id=source_id,
            source_name=source_name or previous.source_name,
            url=url or previous.url,
            status=SourceHealthStatus.DISABLED,
            consecutive_failures=0,
            success_count_24h=previous.success_count_24h,
            failure_count_24h=previous.failure_count_24h,
            avg_latency_ms_24h=previous.avg_latency_ms_24h,
            last_error=error,
        )
        self._health[source_id] = health
        return health

    def record_failure(
        self,
        source_id: str,
        error: SourceError,
        *,
        latency_ms: float | None = None,
        source_name: str | None = None,
        url: str | None = None,
    ) -> SourceHealth:
        previous = self.get(source_id)
        failures = previous.consecutive_failures + 1
        now = self._now()
        stats = self._record_event(source_id, succeeded=False, latency_ms=latency_ms, now=now)
        if failures >= self.failure_threshold:
            status = SourceHealthStatus.COOLING_DOWN
            cooldown_until = now + timedelta(seconds=self.cooldown_seconds)
        else:
            status = SourceHealthStatus.DEGRADED
            cooldown_until = None
        health = SourceHealth(
            source_id=source_id,
            source_name=source_name or error.source_name or previous.source_name,
            url=url or error.url or previous.url,
            status=status,
            consecutive_failures=failures,
            success_count_24h=stats.success_count_24h,
            failure_count_24h=stats.failure_count_24h,
            avg_latency_ms_24h=stats.avg_latency_ms_24h,
            last_success_at=previous.last_success_at,
            last_failure_at=now,
            cooldown_until=cooldown_until,
            last_error=error,
        )
        self._health[source_id] = health
        return health

    def _record_event(
        self,
        source_id: str,
        *,
        succeeded: bool,
        latency_ms: float | None,
        now: datetime,
    ) -> _HealthWindowStats:
        events = self._events.setdefault(source_id, [])
        events.append(
            _HealthEvent(
                occurred_at=_as_utc(now),
                succeeded=succeeded,
                latency_ms=_latency(latency_ms),
            )
        )
        return self._window_stats(source_id, now=now)

    def _window_stats(self, source_id: str, *, now: datetime) -> _HealthWindowStats:
        events = self._events.get(source_id)
        if not events:
            return _HealthWindowStats()
        cutoff = _as_utc(now) - HEALTH_WINDOW
        retained = [event for event in events if _as_utc(event.occurred_at) >= cutoff]
        self._events[source_id] = retained
        latencies = [event.latency_ms for event in retained if event.latency_ms is not None]
        return _HealthWindowStats(
            success_count_24h=sum(1 for event in retained if event.succeeded),
            failure_count_24h=sum(1 for event in retained if not event.succeeded),
            avg_latency_ms_24h=(
                round(sum(latencies) / len(latencies), 3) if latencies else None
            ),
        )


def _with_source_context(
    health: SourceHealth,
    *,
    source_name: str | None,
    url: str | None,
) -> SourceHealth:
    if source_name is None and url is None:
        return health
    return replace(
        health,
        source_name=source_name or health.source_name,
        url=url or health.url,
    )


def _with_window_stats(health: SourceHealth, stats: _HealthWindowStats) -> SourceHealth:
    return replace(
        health,
        success_count_24h=stats.success_count_24h,
        failure_count_24h=stats.failure_count_24h,
        avg_latency_ms_24h=stats.avg_latency_ms_24h,
    )


def _latency(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, float(value))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
