from __future__ import annotations

from dataclasses import dataclass

from business.foundation.models.source import SourceDefinition, SourceError, SourcePipelineMetrics
from business.boards.cross_board.workflows.daily_intelligence.source_event_recorder import SourceEventRecorder
from business.boards.cross_board.workflows.daily_intelligence.source_fetch_records import (
    SourceErrorRuntimeMetadata,
)
from business.boards.cross_board.workflows.daily_intelligence.source_health_flow import SourceHealthFlow


@dataclass(frozen=True)
class SourceFetchErrorHandlingContext:
    source: SourceDefinition
    fetch_latency_ms: float
    event_recorder: SourceEventRecorder
    health_flow: SourceHealthFlow
    metrics: SourcePipelineMetrics


class SourceFetchErrorHandlingService:
    def handle_error(self, error: SourceError, context: SourceFetchErrorHandlingContext) -> None:
        runtime_metadata = SourceErrorRuntimeMetadata.from_error(error)
        context.event_recorder.fetch_failed(
            context.source,
            error=error,
            retryable=runtime_metadata.retryable,
            source_health_affecting=runtime_metadata.source_health_affecting,
            fetch_latency_ms=context.fetch_latency_ms,
        )
        if runtime_metadata.phase == "parse":
            context.event_recorder.parse_failed(
                context.source,
                error=error,
                retryable=runtime_metadata.retryable,
            )
        context.metrics.record_error(error)
        if runtime_metadata.source_health_affecting:
            context.health_flow.record_failure(
                context.source,
                error,
                fetch_latency_ms=context.fetch_latency_ms,
            )

    def handle_errors(
        self,
        errors: list[SourceError],
        context: SourceFetchErrorHandlingContext,
    ) -> None:
        for error in errors:
            self.handle_error(error, context)


__all__ = ["SourceFetchErrorHandlingContext", "SourceFetchErrorHandlingService"]
