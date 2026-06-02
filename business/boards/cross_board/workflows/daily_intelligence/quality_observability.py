from __future__ import annotations

from collections.abc import Mapping
from typing import Any


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
