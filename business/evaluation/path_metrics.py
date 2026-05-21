from __future__ import annotations

from business.boards.cross_board.regression_guard import ORDERED_STAGE_TYPES
from business.evaluation.models import clamp_metric


def path_stage_completeness(path: object) -> float:
    missing = _list_attr(path, "missing_stage_types")
    stage_total = _metadata_number(path, "stage_total", default=len(ORDERED_STAGE_TYPES))
    stage_total = max(1.0, stage_total)
    return clamp_metric((stage_total - len(missing)) / stage_total)


def evidence_precision(path: object) -> float:
    evidence_ids = _list_attr(path, "evidence_relation_ids")
    duplicate_count = _number_attr(path, "duplicate_evidence_count")
    contradiction_count = _number_attr(path, "contradictory_evidence_count")
    if not evidence_ids:
        return 0.0
    useful = max(0.0, len(evidence_ids) - duplicate_count - contradiction_count)
    return clamp_metric(useful / len(evidence_ids))


def contradiction_block_rate(paths: list[object]) -> float:
    contradictory = [path for path in paths if _number_attr(path, "contradictory_evidence_count") > 0.0]
    if not contradictory:
        return 1.0
    blocked = [path for path in contradictory if _is_blocked(path)]
    return clamp_metric(len(blocked) / len(contradictory))


def cross_board_path_metrics(paths: list[object]) -> dict[str, float]:
    if not paths:
        return {
            "path_stage_completeness": 0.0,
            "evidence_precision": 0.0,
            "contradiction_block_rate": 1.0,
        }
    return {
        "path_stage_completeness": clamp_metric(sum(path_stage_completeness(path) for path in paths) / len(paths)),
        "evidence_precision": clamp_metric(sum(evidence_precision(path) for path in paths) / len(paths)),
        "contradiction_block_rate": contradiction_block_rate(paths),
    }


def _is_blocked(path: object) -> bool:
    metadata = getattr(path, "metadata", {}) or {}
    guard = getattr(path, "guard_result", None)
    return bool(getattr(path, "blocking_reasons", None)) or bool(metadata.get("scoring_blocked")) or bool(
        guard is not None and not getattr(guard, "passed", True)
    )


def _list_attr(value: object, name: str) -> list[object]:
    item = getattr(value, name, [])
    return list(item or [])


def _number_attr(value: object, name: str) -> float:
    item = getattr(value, name, 0.0)
    return float(item or 0.0)


def _metadata_number(value: object, name: str, *, default: float) -> float:
    metadata = getattr(value, "metadata", {}) or {}
    item = metadata.get(name, default) if isinstance(metadata, dict) else default
    return float(item or default)
