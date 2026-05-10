from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from domain.sources import SourceError, SourceHealth, SourceHealthStatus


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

    def get(self, source_id: str) -> SourceHealth:
        return self._health.get(source_id, SourceHealth(source_id=source_id))

    def should_skip(self, source_id: str) -> bool:
        health = self.get(source_id)
        return (
            health.status == SourceHealthStatus.COOLING_DOWN
            and health.cooldown_until is not None
            and health.cooldown_until > self._now()
        )

    def record_success(self, source_id: str) -> SourceHealth:
        health = SourceHealth(
            source_id=source_id,
            status=SourceHealthStatus.HEALTHY,
            consecutive_failures=0,
            last_success_at=self._now(),
        )
        self._health[source_id] = health
        return health

    def record_failure(self, source_id: str, error: SourceError) -> SourceHealth:
        previous = self.get(source_id)
        failures = previous.consecutive_failures + 1
        now = self._now()
        if failures >= self.failure_threshold:
            status = SourceHealthStatus.COOLING_DOWN
            cooldown_until = now + timedelta(seconds=self.cooldown_seconds)
        else:
            status = SourceHealthStatus.DEGRADED
            cooldown_until = None
        health = SourceHealth(
            source_id=source_id,
            status=status,
            consecutive_failures=failures,
            last_success_at=previous.last_success_at,
            last_failure_at=now,
            cooldown_until=cooldown_until,
            last_error=error,
        )
        self._health[source_id] = health
        return health
