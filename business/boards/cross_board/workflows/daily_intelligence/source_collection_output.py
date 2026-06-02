from __future__ import annotations

from typing import Any

from business.foundation.models.source import (
    SourceError,
    SourceFetchRequest,
    SourceFetchResult,
    SourcePipelineEvent,
    SourcePipelineMetrics,
)
from business.layers.signal.source_processing import (
    build_source_connector_dispatch_report,
    build_source_coverage_report,
    build_source_error_policy_report,
    build_source_fallback_report,
    build_source_health_report,
)
from business.boards.cross_board.workflows.daily_intelligence.buffer_key_aliases import (
    with_namespaced_aliases,
)


def build_source_collection_output(
    *,
    raw_items: list[Any],
    source_errors: list[SourceError],
    skipped_sources: list[dict[str, Any]],
    failed_sources: list[dict[str, Any]],
    source_fetch_requests: list[SourceFetchRequest],
    source_fetch_results: list[SourceFetchResult],
    source_health_updates: list[Any],
    source_events: list[SourcePipelineEvent],
    source_pipeline_metrics: SourcePipelineMetrics,
    source_selection_report: Any,
) -> dict[str, Any]:
    return with_namespaced_aliases({
        "raw_items": raw_items,
        "source_errors": source_errors,
        "skipped_sources": skipped_sources,
        "failed_sources": failed_sources,
        "source_fetch_requests": source_fetch_requests,
        "source_fetch_results": source_fetch_results,
        "source_health_updates": source_health_updates,
        "source_health_report": build_source_health_report(source_health_updates),
        "source_events": source_events,
        "source_pipeline_metrics": source_pipeline_metrics,
        "source_connector_dispatch_report": build_source_connector_dispatch_report(
            source_fetch_requests,
            source_fetch_results,
        ),
        "source_error_policy_report": build_source_error_policy_report(source_errors),
        "source_fallback_report": build_source_fallback_report(
            raw_items=raw_items,
            source_errors=source_errors,
            source_selection_report=source_selection_report,
        ),
        "source_selection_report": source_selection_report,
        "source_coverage_report": build_source_coverage_report(
            source_pipeline_metrics,
            source_errors=source_errors,
            skipped_sources=skipped_sources,
            failed_sources=failed_sources,
        ),
    })


def record_all_sources_failed(
    *,
    source_errors: list[SourceError],
    failed_sources: list[dict[str, Any]],
    source_events: list[SourcePipelineEvent],
    source_pipeline_metrics: SourcePipelineMetrics,
    source_event: Any,
) -> None:
    all_sources_error = SourceError(
        source_id="source_pipeline",
        source_name="Source Pipeline",
        error_type="all_sources_failed",
        error_message="all enabled sources failed or returned no valid items",
        retryable=False,
        metadata={
            "retryable": False,
            "source_health_affecting": False,
            "workflow_blocking": True,
            "sources_total": source_pipeline_metrics.sources_total,
            "sources_failed": source_pipeline_metrics.sources_failed,
            "sources_skipped": source_pipeline_metrics.sources_skipped,
        },
    )
    source_errors.append(all_sources_error)
    failed_sources.append(all_sources_error.to_dict())
    source_pipeline_metrics.record_error(all_sources_error)
    source_events.append(
        source_event(
            "source_fetch_failed",
            error_type="all_sources_failed",
            retryable=False,
            sources_total=source_pipeline_metrics.sources_total,
            sources_failed=source_pipeline_metrics.sources_failed,
            sources_skipped=source_pipeline_metrics.sources_skipped,
        )
    )
