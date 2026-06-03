from __future__ import annotations

from business.foundation.models.source import (
    SourceDefinition,
    SourceError,
    SourcePipelineEvent,
    SourcePipelineMetrics,
    SourceReliability,
    SourceType,
)
from business.layers.signal.source_health import BasicSourceHealthManager
from business.boards.cross_board.workflows.daily_intelligence.source_error_handling import (
    SourceFetchErrorHandlingContext,
    SourceFetchErrorHandlingService,
)
from business.boards.cross_board.workflows.daily_intelligence.source_event_recorder import (
    SourceEventRecorder,
)
from business.boards.cross_board.workflows.daily_intelligence.source_health_flow import (
    SourceHealthFlow,
)


def test_source_fetch_error_handling_records_parse_error_events_metrics_and_health() -> None:
    source = _source()
    error = SourceError(
        source_id=source.source_id,
        source_name=source.name,
        error_type="parse_error",
        error_message="Could not parse feed.",
        retryable=False,
        metadata={
            "source_error_runtime_metadata": {
                "phase": "parse",
                "source_health_affecting": True,
            },
        },
    )
    source_events: list[SourcePipelineEvent] = []
    event_recorder = SourceEventRecorder(source_events)
    health_updates = []
    health_flow = SourceHealthFlow(
        health_manager=BasicSourceHealthManager(failure_threshold=1, cooldown_seconds=300),
        events=event_recorder,
        health_updates=health_updates,
    )
    metrics = SourcePipelineMetrics()

    SourceFetchErrorHandlingService().handle_error(
        error,
        SourceFetchErrorHandlingContext(
            source=source,
            fetch_latency_ms=12.5,
            event_recorder=event_recorder,
            health_flow=health_flow,
            metrics=metrics,
        ),
    )

    assert [event.event_type for event in source_events] == [
        "source_fetch_failed",
        "source_parse_failed",
        "source_health_updated",
        "source_cooldown_started",
    ]
    assert source_events[0].metadata == {
        "error_type": "parse_error",
        "retryable": False,
        "source_health_affecting": True,
        "fetch_latency_ms": 12.5,
    }
    assert source_events[1].metadata == {
        "error_type": "parse_error",
        "retryable": False,
    }
    assert metrics.errors_by_type == {"parse_error": 1}
    assert len(health_updates) == 1


def test_source_fetch_error_handling_skips_health_update_for_non_affecting_errors() -> None:
    source = _source()
    error = SourceError(
        source_id=source.source_id,
        source_name=source.name,
        error_type="rate_limited",
        error_message="Rate limited.",
        retryable=True,
        metadata={
            "source_error_runtime_metadata": {
                "source_health_affecting": False,
            },
        },
    )
    source_events: list[SourcePipelineEvent] = []
    event_recorder = SourceEventRecorder(source_events)
    health_updates = []
    health_flow = SourceHealthFlow(
        health_manager=BasicSourceHealthManager(failure_threshold=1, cooldown_seconds=300),
        events=event_recorder,
        health_updates=health_updates,
    )
    metrics = SourcePipelineMetrics()

    SourceFetchErrorHandlingService().handle_errors(
        [error],
        SourceFetchErrorHandlingContext(
            source=source,
            fetch_latency_ms=9.0,
            event_recorder=event_recorder,
            health_flow=health_flow,
            metrics=metrics,
        ),
    )

    assert [event.event_type for event in source_events] == ["source_fetch_failed"]
    assert source_events[0].metadata["source_health_affecting"] is False
    assert metrics.errors_by_type == {"rate_limited": 1}
    assert health_updates == []


def _source() -> SourceDefinition:
    return SourceDefinition(
        source_id="feed",
        name="Feed",
        source_type=SourceType.RSS,
        url="https://example.com/feed.xml",
        reliability=SourceReliability.HIGH,
    )
