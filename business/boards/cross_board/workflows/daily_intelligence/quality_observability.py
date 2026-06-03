from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_COUNT_FIELDS = (
    "sample_count",
    "block_count",
    "rewrite_count",
    "human_review_count",
    "memory_conflict_count",
    "memory_conflict_run_count",
)


def quality_gate_observability_metrics(
    *,
    blocked: bool,
    rewrite_required: bool,
    human_review_required: bool,
    memory_quality_result: Any | None = None,
) -> dict[str, int | float]:
    sample_count = 1
    block_count = int(blocked)
    rewrite_count = int(rewrite_required)
    human_review_count = int(human_review_required)
    memory_conflict_count = _memory_conflict_count(memory_quality_result)
    memory_conflict_run_count = int(memory_conflict_count > 0)
    return {
        "sample_count": sample_count,
        "block_count": block_count,
        "rewrite_count": rewrite_count,
        "human_review_count": human_review_count,
        "memory_conflict_count": memory_conflict_count,
        "memory_conflict_run_count": memory_conflict_run_count,
        "block_rate": _rate(block_count, sample_count),
        "rewrite_rate": _rate(rewrite_count, sample_count),
        "human_review_rate": _rate(human_review_count, sample_count),
        "memory_conflict_rate": _rate(memory_conflict_run_count, sample_count),
    }


def aggregate_quality_gate_observability_metrics(
    metrics: Any,
) -> dict[str, int | float]:
    aggregate = {field: 0 for field in _COUNT_FIELDS}
    for entry in _metric_entries(metrics):
        aggregate["sample_count"] += _entry_count(entry, "sample_count", default=1)
        aggregate["block_count"] += _entry_count(
            entry,
            "block_count",
            default=int(_entry_bool(entry, "blocked")),
        )
        aggregate["rewrite_count"] += _entry_count(
            entry,
            "rewrite_count",
            default=int(_entry_bool(entry, "rewrite_required")),
        )
        aggregate["human_review_count"] += _entry_count(
            entry,
            "human_review_count",
            default=int(_entry_bool(entry, "human_review_required")),
        )
        memory_conflict_count = _entry_count(entry, "memory_conflict_count", default=0)
        aggregate["memory_conflict_count"] += memory_conflict_count
        aggregate["memory_conflict_run_count"] += _entry_count(
            entry,
            "memory_conflict_run_count",
            default=int(memory_conflict_count > 0),
        )

    sample_count = aggregate["sample_count"]
    return {
        **aggregate,
        "block_rate": _rate(aggregate["block_count"], sample_count),
        "rewrite_rate": _rate(aggregate["rewrite_count"], sample_count),
        "human_review_rate": _rate(aggregate["human_review_count"], sample_count),
        "memory_conflict_rate": _rate(
            aggregate["memory_conflict_run_count"],
            sample_count,
        ),
    }


def _metric_entries(metrics: Any) -> list[Mapping[str, Any]]:
    if metrics is None:
        return []
    if isinstance(metrics, Mapping):
        return [metrics]
    if isinstance(metrics, (str, bytes)):
        return []
    try:
        iterable = iter(metrics)
    except TypeError:
        entry = _metric_entry(metrics)
        return [entry] if entry is not None else []
    entries: list[Mapping[str, Any]] = []
    for item in iterable:
        entry = _metric_entry(item)
        if entry is not None:
            entries.append(entry)
    return entries


def _metric_entry(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        projected = to_dict()
        if isinstance(projected, Mapping):
            return projected
    return None


def _entry_count(entry: Mapping[str, Any], field: str, *, default: int) -> int:
    value = _non_negative_int(entry.get(field))
    if value is not None:
        return value
    return default


def _entry_bool(entry: Mapping[str, Any], field: str) -> bool:
    return entry.get(field) is True


def _memory_conflict_count(memory_quality_result: Any | None) -> int:
    if not isinstance(memory_quality_result, Mapping):
        return 0
    metadata = memory_quality_result.get("metadata")
    if isinstance(metadata, Mapping):
        conflict_count = _non_negative_int(metadata.get("conflict_count"))
        if conflict_count is not None:
            return conflict_count
    return sum(
        1
        for issue in memory_quality_result.get("issues") or []
        if isinstance(issue, Mapping) and _is_memory_conflict_issue(issue.get("issue_type"))
    )


def _is_memory_conflict_issue(issue_type: Any) -> bool:
    normalized = str(issue_type or "").strip().lower()
    return "conflict" in normalized or "contradict" in normalized


def _non_negative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _rate(count: int, sample_count: int) -> float:
    if sample_count <= 0:
        return 0.0
    return count / sample_count


__all__ = [
    "aggregate_quality_gate_observability_metrics",
    "quality_gate_observability_metrics",
]
