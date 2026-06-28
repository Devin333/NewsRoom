from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from framework.shared.json import to_jsonable

SCORE_BREAKDOWN_COMPONENTS = (
    "child_similarity",
    "parent_relevance",
    "field_score",
    "section_heading_score",
    "position_bonus",
    "rerank_score",
    "final_score",
)


def summarize_score_breakdowns(
    breakdowns: Iterable[Mapping[str, Any]],
    *,
    top_k: int | None = None,
) -> dict[str, Any]:
    values_by_component: dict[str, list[float]] = {}
    evidence_count = 0
    for index, breakdown in enumerate(breakdowns):
        if top_k is not None and index >= top_k:
            break
        cleaned = _numeric_breakdown(breakdown)
        if not cleaned:
            continue
        evidence_count += 1
        for component, value in cleaned.items():
            values_by_component.setdefault(component, []).append(value)

    components = {
        component: _component_stats(values)
        for component, values in sorted(values_by_component.items(), key=_component_sort_key)
    }
    return to_jsonable({
        "evidence_count": evidence_count,
        "top_k": top_k,
        "components": components,
    })


def _numeric_breakdown(breakdown: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, raw in breakdown.items():
        if isinstance(raw, bool):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        out[str(key)] = value
    return out


def _component_stats(values: list[float]) -> dict[str, float | int]:
    count = len(values)
    avg = sum(values) / count if count else 0.0
    return {
        "count": count,
        "avg": round(avg, 6),
        "min": round(min(values), 6) if values else 0.0,
        "max": round(max(values), 6) if values else 0.0,
    }


def _component_sort_key(item: tuple[str, list[float]]) -> tuple[int, str]:
    component = item[0]
    order = SCORE_BREAKDOWN_COMPONENTS.index(component) if component in SCORE_BREAKDOWN_COMPONENTS else 999
    return (order, component)


__all__ = ["SCORE_BREAKDOWN_COMPONENTS", "summarize_score_breakdowns"]
