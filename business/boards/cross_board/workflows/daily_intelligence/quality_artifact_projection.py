from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    daily_output_contains,
    daily_output_value,
)


def quality_manifest_fields(output: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}

    if daily_output_contains(output, "report_quality_summary"):
        summary = daily_output_value(output, "report_quality_summary")
        if hasattr(summary, "quality_score"):
            fields["quality_score"] = summary.quality_score
        elif isinstance(summary, Mapping):
            fields["quality_score"] = summary.get("quality_score")

    if daily_output_contains(output, "quality_events"):
        fields["quality_event_count"] = len(daily_output_value(output, "quality_events"))

    quality_result = daily_output_value(output, "quality_result")
    route = _field_value(quality_result, "route")
    if route is None:
        route = daily_output_value(output, "quality_route")
    if route is not None:
        fields["quality_route"] = route

    decision = _field_value(quality_result, "decision")
    if decision is not None:
        fields["quality_decision"] = decision

    return fields


def _field_value(value: Any, field_name: str) -> Any:
    if hasattr(value, field_name):
        return getattr(value, field_name)
    if isinstance(value, Mapping):
        return value.get(field_name)
    return None


__all__ = ["quality_manifest_fields"]
