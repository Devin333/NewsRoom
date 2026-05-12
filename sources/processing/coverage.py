from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from domain.sources import SourceCoverageReport, SourceError, SourcePipelineMetrics


def build_source_coverage_report(
    metrics: SourcePipelineMetrics,
    *,
    source_errors: Iterable[SourceError | Mapping[str, Any]] = (),
    skipped_sources: Iterable[Mapping[str, Any]] = (),
    failed_sources: Iterable[Mapping[str, Any]] = (),
) -> SourceCoverageReport:
    selected_count = metrics.sources_total
    outcome_count = metrics.sources_fetched + metrics.sources_failed + metrics.sources_skipped
    attempted_count = min(selected_count, outcome_count)
    unattempted_count = max(0, selected_count - attempted_count)
    error_count = sum(1 for _ in source_errors)
    skipped_source_ids = _source_ids(skipped_sources)
    failed_source_ids = _source_ids(failed_sources, exclude={"source_pipeline"})
    partial_reasons = _partial_reasons(
        metrics,
        unattempted_source_count=unattempted_count,
        error_count=error_count,
    )

    return SourceCoverageReport(
        coverage_status=_coverage_status(metrics, unattempted_source_count=unattempted_count),
        selected_source_count=selected_count,
        attempted_source_count=attempted_count,
        fetched_source_count=metrics.sources_fetched,
        failed_source_count=metrics.sources_failed,
        skipped_source_count=metrics.sources_skipped,
        unattempted_source_count=unattempted_count,
        raw_item_count=metrics.raw_items_count,
        normalized_item_count=metrics.normalized_items_count,
        deduplicated_item_count=metrics.deduplicated_items_count,
        ranked_item_count=metrics.ranked_items_count,
        duplicate_item_count=metrics.duplicate_count,
        error_count=error_count,
        fetch_success_ratio=_ratio(metrics.sources_fetched, selected_count),
        attempted_source_ratio=_ratio(attempted_count, selected_count),
        item_yield_ratio=_ratio(metrics.raw_items_count, selected_count),
        avg_fetch_latency_ms=metrics.avg_fetch_latency_ms,
        sources_by_type=dict(metrics.sources_by_type),
        sources_by_reliability=dict(metrics.sources_by_reliability),
        fetched_by_type=dict(metrics.fetched_by_type),
        failed_by_type=dict(metrics.failed_by_type),
        skipped_by_type=dict(metrics.skipped_by_type),
        items_by_source=dict(metrics.items_by_source),
        items_by_source_type=dict(metrics.items_by_source_type),
        items_by_reliability=dict(metrics.items_by_reliability),
        errors_by_type=dict(metrics.errors_by_type),
        skipped_source_ids=skipped_source_ids,
        failed_source_ids=failed_source_ids,
        partial_reasons=partial_reasons,
    )


def _coverage_status(metrics: SourcePipelineMetrics, *, unattempted_source_count: int) -> str:
    if metrics.sources_total <= 0 or metrics.raw_items_count <= 0:
        return "empty"
    if metrics.sources_failed or metrics.sources_skipped or unattempted_source_count:
        return "partial"
    return "covered"


def _partial_reasons(
    metrics: SourcePipelineMetrics,
    *,
    unattempted_source_count: int,
    error_count: int,
) -> list[str]:
    reasons: list[str] = []
    if metrics.sources_total <= 0:
        reasons.append("no_sources_selected")
    if metrics.raw_items_count <= 0:
        reasons.append("no_raw_items")
    if metrics.sources_failed:
        reasons.append("source_failures")
    if metrics.sources_skipped:
        reasons.append("source_skips")
    if unattempted_source_count:
        reasons.append("unattempted_sources")
    if error_count:
        reasons.append("source_errors")
    return reasons


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _source_ids(
    values: Iterable[Mapping[str, Any]],
    *,
    exclude: set[str] | None = None,
) -> list[str]:
    excluded = exclude or set()
    seen: set[str] = set()
    source_ids: list[str] = []
    for value in values:
        source_id = value.get("source_id")
        if not source_id:
            continue
        normalized = str(source_id)
        if normalized in excluded or normalized in seen:
            continue
        seen.add(normalized)
        source_ids.append(normalized)
    return source_ids
