from __future__ import annotations

from typing import Any

from framework.workflow import ScopedDataBuffer
from business.foundation.models.source import SourceError, SourcePipelineEvent
from infrastructure.external.sources.errors import classify_source_exception
from business.layers.signal.source_processing import (
    build_source_coverage_report,
    build_source_freshness_report,
    build_source_governance_report,
    build_source_quality_summary_report,
    build_source_ranking_scores,
    build_source_traceability_report,
    deduplicate_with_result,
    normalize_item,
    rank_items,
)


class AllSourcesFailedError(RuntimeError):
    pass


def source_event(event_type: str, source_id: str | None = None, **metadata: Any) -> SourcePipelineEvent:
    return SourcePipelineEvent(
        event_type=event_type,
        source_id=source_id,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def require_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    raw_items = buffer.read("raw_items")
    if raw_items:
        return {"source_collection_status": "ready"}

    source_errors = buffer.read("source_errors")
    error_types = [
        error.error_type if hasattr(error, "error_type") else error.get("error_type", "unknown")
        for error in source_errors
    ]
    raise AllSourcesFailedError(
        "all_sources_failed: no source items collected from enabled sources "
        f"(errors: {', '.join(error_types)})"
    )


def normalize_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    raw_items = buffer.read("raw_items")
    source_errors = list(buffer.read("source_errors"))
    normalized_items = []
    normalization_errors: list[SourceError] = []
    for raw_item in raw_items:
        try:
            normalized_items.append(normalize_item(raw_item))
        except Exception as exc:
            error = _processing_source_error(raw_item, exc, phase="normalize")
            normalization_errors.append(error)
            source_errors.append(error)
    source_events = list(buffer.read("source_events"))
    source_events.append(
        source_event("source_normalized", input_count=len(raw_items), output_count=len(normalized_items))
    )
    for error in normalization_errors:
        source_events.append(
            source_event(
                "source_normalization_failed",
                error.source_id,
                error_type=error.error_type,
                retryable=False,
            )
        )
    metrics = buffer.read("source_pipeline_metrics")
    metrics.normalized_items_count = len(normalized_items)
    for error in normalization_errors:
        metrics.record_error(error)
    return {
        "normalized_items": normalized_items,
        "source_errors": source_errors,
        "source_events": source_events,
        "source_pipeline_metrics": metrics,
    }


def deduplicate_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    normalized_items = buffer.read("normalized_items")
    source_errors = list(buffer.read("source_errors"))
    try:
        dedup_result = deduplicate_with_result(normalized_items)
        deduplicated_items = dedup_result.kept_items
        source_duplicate_groups = [group.to_dict() for group in dedup_result.duplicate_groups]
        duplicate_count = len(dedup_result.dropped_items)
        dedup_errors: list[SourceError] = []
    except Exception as exc:
        error = _pipeline_processing_error(exc, phase="dedup")
        dedup_errors = [error]
        source_errors.append(error)
        deduplicated_items = []
        source_duplicate_groups = []
        duplicate_count = 0
    source_events = list(buffer.read("source_events"))
    metrics = buffer.read("source_pipeline_metrics")
    metrics.deduplicated_items_count = len(deduplicated_items)
    metrics.duplicate_count = duplicate_count
    for error in dedup_errors:
        metrics.record_error(error)
    source_events.append(
        source_event(
            "source_deduplicated",
            input_count=len(normalized_items),
            output_count=len(deduplicated_items),
            duplicate_count=metrics.duplicate_count,
            duplicate_group_count=len(source_duplicate_groups),
        )
    )
    for error in dedup_errors:
        source_events.append(source_event("source_dedup_failed", error_type=error.error_type, retryable=False))
    return {
        "deduplicated_items": deduplicated_items,
        "source_errors": source_errors,
        "source_duplicate_groups": source_duplicate_groups,
        "source_events": source_events,
        "source_pipeline_metrics": metrics,
    }


def rank_sources(buffer: ScopedDataBuffer) -> dict[str, Any]:
    request = buffer.read("request")
    deduplicated_items = buffer.read("deduplicated_items")
    source_errors = list(buffer.read("source_errors"))
    try:
        ranked_items = rank_items(deduplicated_items, topic=request["topic"])
        ranking_errors: list[SourceError] = []
    except Exception as exc:
        error = _pipeline_processing_error(exc, phase="rank")
        source_errors.append(error)
        ranking_errors = [error]
        ranked_items = []
    source_events = list(buffer.read("source_events"))
    source_events.append(
        source_event(
            "source_ranked",
            input_count=len(deduplicated_items),
            output_count=len(ranked_items),
            topic=request["topic"],
        )
    )
    for error in ranking_errors:
        source_events.append(source_event("source_ranking_failed", error_type=error.error_type, retryable=False))
    metrics = buffer.read("source_pipeline_metrics")
    metrics.ranked_items_count = len(ranked_items)
    for error in ranking_errors:
        metrics.record_error(error)
    source_quality_scores = [
        ranked.metadata["source_quality"]
        for ranked in ranked_items
        if "source_quality" in ranked.metadata
    ]
    source_ranking_scores = build_source_ranking_scores(ranked_items)
    source_freshness_report = build_source_freshness_report(ranked_items)
    source_traceability_report = build_source_traceability_report(ranked_items)
    source_quality_summary_report = build_source_quality_summary_report(source_quality_scores)
    return {
        "ranked_items": ranked_items,
        "source_errors": source_errors,
        "source_events": source_events,
        "source_pipeline_metrics": metrics,
        "source_coverage_report": build_source_coverage_report(
            metrics,
            source_errors=source_errors,
            skipped_sources=buffer.read("skipped_sources"),
            failed_sources=buffer.read("failed_sources"),
        ),
        "source_quality_scores": source_quality_scores,
        "source_quality_summary_report": source_quality_summary_report,
        "source_ranking_scores": source_ranking_scores,
        "source_freshness_report": source_freshness_report,
        "source_traceability_report": source_traceability_report,
        "source_governance_report": build_source_governance_report(
            source_quality_scores=source_quality_scores,
            source_selection_report=buffer.read("source_selection_report"),
        ),
    }


def _processing_source_error(raw_item: Any, exc: Exception, *, phase: str) -> SourceError:
    classification = classify_source_exception(exc, phase=phase)
    source_id = str(getattr(raw_item, "source_id", "source_pipeline") or "source_pipeline")
    return SourceError(
        source_id=source_id,
        source_name=getattr(raw_item, "source_name", None),
        error_type=classification.error_type,
        error_message=str(exc),
        url=getattr(raw_item, "url", None),
        retryable=classification.retryable,
        metadata={
            "phase": phase,
            "source_item_id": getattr(raw_item, "source_item_id", None),
            "retryable": classification.retryable,
            "source_health_affecting": classification.source_health_affecting,
            "workflow_blocking": classification.workflow_blocking,
            "original_exception_type": type(exc).__name__,
        },
    )


def _pipeline_processing_error(exc: Exception, *, phase: str) -> SourceError:
    classification = classify_source_exception(exc, phase=phase)
    return SourceError(
        source_id="source_pipeline",
        source_name="Source Pipeline",
        error_type=classification.error_type,
        error_message=str(exc),
        retryable=classification.retryable,
        metadata={
            "phase": phase,
            "retryable": classification.retryable,
            "source_health_affecting": classification.source_health_affecting,
            "workflow_blocking": classification.workflow_blocking,
            "original_exception_type": type(exc).__name__,
        },
    )
