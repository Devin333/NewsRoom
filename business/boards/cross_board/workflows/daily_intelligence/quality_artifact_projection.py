from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    project_daily_output_for_quality_artifacts,
)


def quality_manifest_fields(output: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    quality_output = project_daily_output_for_quality_artifacts(output)

    if "report_quality_summary" in quality_output:
        summary = quality_output["report_quality_summary"]
        if hasattr(summary, "quality_score"):
            fields["quality_score"] = summary.quality_score
        elif isinstance(summary, Mapping):
            fields["quality_score"] = summary.get("quality_score")

    if "quality_events" in quality_output:
        fields["quality_event_count"] = len(quality_output["quality_events"])

    quality_result = quality_output.get("quality_result")
    route = _field_value(quality_result, "route")
    if route is None:
        route = quality_output.get("quality_route")
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
