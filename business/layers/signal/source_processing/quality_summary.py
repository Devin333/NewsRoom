from __future__ import annotations

from typing import Any

from business.foundation.models.source import SourceQualitySummaryReport


LOW_QUALITY_THRESHOLD = 0.65


def build_source_quality_summary_report(
    source_quality_scores: list[Any],
) -> SourceQualitySummaryReport:
    rows: list[dict[str, Any]] = []
    penalty_counts: dict[str, int] = {}
    quality_values: list[float] = []

    for score in source_quality_scores:
        quality_score = _float(_value(score, "quality_score"), default=0.0)
        traceability_score = _float(_value(score, "traceability_score"), default=0.0)
        penalties = [str(penalty) for penalty in (_value(score, "penalties") or [])]
        for penalty in penalties:
            penalty_counts[penalty] = penalty_counts.get(penalty, 0) + 1
        quality_values.append(quality_score)
        rows.append(
            {
                "normalized_item_id": _value(score, "normalized_item_id"),
                "source_item_id": _value(score, "source_item_id"),
                "source_id": _value(score, "source_id"),
                "quality_score": quality_score,
                "traceability_score": traceability_score,
                "penalties": penalties,
                "low_quality": quality_score < LOW_QUALITY_THRESHOLD,
                "weak_traceability": traceability_score < 1.0,
            }
        )

    return SourceQualitySummaryReport(
        item_count=len(rows),
        average_quality_score=(
            round(sum(quality_values) / len(quality_values), 4) if quality_values else None
        ),
        min_quality_score=min(quality_values) if quality_values else None,
        max_quality_score=max(quality_values) if quality_values else None,
        low_quality_count=sum(1 for row in rows if row["low_quality"]),
        weak_traceability_count=sum(1 for row in rows if row["weak_traceability"]),
        penalty_counts=penalty_counts,
        rows=rows,
    )


def _value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
