from __future__ import annotations

from business.foundation.models.source import SourceDefinition, SourceError, SourceHealth, SourcePipelineEvent
from business.boards.cross_board.workflows.daily_intelligence.source_fetch_records import dt
from business.boards.cross_board.workflows.daily_intelligence.source_processing import source_event


class SourceEventRecorder:
    def __init__(self, events: list[SourcePipelineEvent]) -> None:
        self.events = events

    def fetch_skipped(
        self,
        source: SourceDefinition,
        *,
        reason: str,
        cooldown_until: object | None = None,
        next_fetch_at: object | None = None,
        last_success_at: object | None = None,
    ) -> None:
        self._append(
            "source_fetch_skipped",
            source.source_id,
            reason=reason,
            cooldown_until=dt(cooldown_until),
            next_fetch_at=dt(next_fetch_at),
            last_success_at=dt(last_success_at),
        )

    def health_updated(self, health: SourceHealth) -> None:
        self._append(
            "source_health_updated",
            health.source_id,
            status=health.status.value,
            consecutive_failures=health.consecutive_failures,
        )

    def probe_started(self, source: SourceDefinition, health: SourceHealth) -> None:
        self._append(
            "source_probe_started",
            source.source_id,
            cooldown_until=dt(health.cooldown_until),
            consecutive_failures=health.consecutive_failures,
        )

    def fetch_started(self, source: SourceDefinition) -> None:
        self._append(
            "source_fetch_started",
            source.source_id,
            source_type=source.source_type.value,
            url=source.url,
        )

    def parse_started(self, source: SourceDefinition) -> None:
        self._append(
            "source_parse_started",
            source.source_id,
            source_type=source.source_type.value,
        )

    def fetch_succeeded(
        self,
        source: SourceDefinition,
        *,
        item_count: int,
        fetch_latency_ms: int,
    ) -> None:
        self._append(
            "source_fetch_succeeded",
            source.source_id,
            item_count=item_count,
            fetch_latency_ms=fetch_latency_ms,
        )

    def parse_succeeded(self, source: SourceDefinition, *, item_count: int) -> None:
        self._append(
            "source_parse_succeeded",
            source.source_id,
            item_count=item_count,
        )

    def probe_succeeded(
        self,
        source: SourceDefinition,
        *,
        item_count: int,
        fetch_latency_ms: int,
        health: SourceHealth,
    ) -> None:
        self._append(
            "source_probe_succeeded",
            source.source_id,
            item_count=item_count,
            fetch_latency_ms=fetch_latency_ms,
            status=health.status.value,
        )

    def probe_failed(
        self,
        source: SourceDefinition,
        *,
        error_type: str,
        error_count: int,
        fetch_latency_ms: int,
    ) -> None:
        self._append(
            "source_probe_failed",
            source.source_id,
            error_type=error_type,
            error_count=error_count,
            fetch_latency_ms=fetch_latency_ms,
        )

    def fetch_failed(
        self,
        source: SourceDefinition,
        *,
        error: SourceError,
        retryable: bool,
        source_health_affecting: bool,
        fetch_latency_ms: int,
    ) -> None:
        self._append(
            "source_fetch_failed",
            source.source_id,
            error_type=error.error_type,
            retryable=retryable,
            source_health_affecting=source_health_affecting,
            fetch_latency_ms=fetch_latency_ms,
        )

    def parse_failed(
        self,
        source: SourceDefinition,
        *,
        error: SourceError,
        retryable: bool,
    ) -> None:
        self._append(
            "source_parse_failed",
            source.source_id,
            error_type=error.error_type,
            retryable=retryable,
        )

    def cooldown_started(self, health: SourceHealth) -> None:
        self._append(
            "source_cooldown_started",
            health.source_id,
            cooldown_until=dt(health.cooldown_until),
            consecutive_failures=health.consecutive_failures,
        )

    def _append(self, event_type: str, source_id: str | None = None, **metadata: object) -> None:
        self.events.append(source_event(event_type, source_id, **metadata))
