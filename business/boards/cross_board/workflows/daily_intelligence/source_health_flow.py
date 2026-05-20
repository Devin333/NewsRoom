from __future__ import annotations

from dataclasses import dataclass

from business.foundation.models.source import SourceDefinition, SourceError, SourceHealth, SourceHealthStatus
from business.layers.signal.source_health import BasicSourceHealthManager, SourceFetchDecision
from business.boards.cross_board.workflows.daily_intelligence.source_event_recorder import SourceEventRecorder
from business.boards.cross_board.workflows.daily_intelligence.source_fetch_records import dt


@dataclass(frozen=True)
class SourceSkipDecision:
    should_skip: bool
    fetch_decision: SourceFetchDecision
    reason: str | None = None
    metadata: dict[str, object] | None = None


class SourceHealthFlow:
    def __init__(
        self,
        *,
        health_manager: BasicSourceHealthManager,
        events: SourceEventRecorder,
        health_updates: list[SourceHealth],
    ) -> None:
        self.health_manager = health_manager
        self.events = events
        self.health_updates = health_updates

    def decide_fetch(self, source: SourceDefinition) -> SourceSkipDecision:
        fetch_decision = self.health_manager.fetch_decision(
            source.source_id,
            source_name=source.name,
            url=source.url,
            min_interval_seconds=source.fetch_interval_seconds,
        )
        if fetch_decision.should_fetch:
            return SourceSkipDecision(should_skip=False, fetch_decision=fetch_decision)

        health = fetch_decision.health
        reason = fetch_decision.skip_reason or "skipped"
        metadata = {
            "source_id": source.source_id,
            "source_name": source.name,
            "url": source.url,
            "reason": reason,
            "cooldown_until": dt(fetch_decision.cooldown_until),
            "next_fetch_at": dt(fetch_decision.next_fetch_at),
            "last_success_at": dt(health.last_success_at),
        }
        self.health_updates.append(health)
        self.events.fetch_skipped(
            source,
            reason=reason,
            cooldown_until=fetch_decision.cooldown_until,
            next_fetch_at=fetch_decision.next_fetch_at,
            last_success_at=health.last_success_at,
        )
        self.events.health_updated(health)
        return SourceSkipDecision(
            should_skip=True,
            fetch_decision=fetch_decision,
            reason=reason,
            metadata={key: value for key, value in metadata.items() if value is not None},
        )

    def probe_started(self, source: SourceDefinition) -> bool:
        is_probe = self.health_manager.should_probe(source.source_id)
        if not is_probe:
            return False
        health = self.health_manager.get(
            source.source_id,
            source_name=source.name,
            url=source.url,
        )
        self.events.probe_started(source, health)
        return True

    def record_success(
        self,
        source: SourceDefinition,
        *,
        fetch_latency_ms: int,
        is_probe: bool,
        item_count: int,
    ) -> SourceHealth:
        health = self.health_manager.record_success(
            source.source_id,
            latency_ms=fetch_latency_ms,
            source_name=source.name,
            url=source.url,
        )
        self.health_updates.append(health)
        self.events.health_updated(health)
        if is_probe:
            self.events.probe_succeeded(
                source,
                item_count=item_count,
                fetch_latency_ms=fetch_latency_ms,
                health=health,
            )
        return health

    def record_failure(
        self,
        source: SourceDefinition,
        error: SourceError,
        *,
        fetch_latency_ms: int,
    ) -> SourceHealth:
        health = self.health_manager.record_failure(
            source.source_id,
            error,
            latency_ms=fetch_latency_ms,
            source_name=source.name,
            url=source.url,
        )
        self.health_updates.append(health)
        self.events.health_updated(health)
        if health.status == SourceHealthStatus.DOWN:
            self.events.cooldown_started(health)
        return health
