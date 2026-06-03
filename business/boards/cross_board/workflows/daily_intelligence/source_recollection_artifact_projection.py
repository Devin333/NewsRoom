from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    daily_output_contains,
    daily_output_value,
)


SOURCE_RECOLLECTION_EXECUTION_REPORT_ARTIFACT = (
    "source_recollection/execution_report.json"
)
SOURCE_RECOLLECTION_PROFILE_ARTIFACT = "source_recollection/profile.json"
SOURCE_RECOLLECTION_EXECUTION_PLAN_ARTIFACT = (
    "source_recollection/execution_plan.json"
)
SOURCE_RECOLLECTION_QUALITY_ASSESSMENT_ARTIFACT = (
    "source_recollection/quality_assessment.json"
)


def source_recollection_manifest_summary(
    output: Mapping[str, Any],
) -> dict[str, Any] | None:
    report = daily_output_value(output, "source_recollection_execution_report")
    if report is None:
        return None

    summary = {
        "plan_id": _field_value(report, "plan_id"),
        "status": _field_value(report, "status"),
        "task_count": _int_value(_field_value(report, "task_count")),
        "raw_item_count": _int_value(_field_value(report, "raw_item_count")),
        "error_count": _int_value(_field_value(report, "error_count")),
        "fetch_request_count": _int_value(_field_value(report, "fetch_request_count")),
        "fetch_result_count": _int_value(_field_value(report, "fetch_result_count")),
        "artifact": SOURCE_RECOLLECTION_EXECUTION_REPORT_ARTIFACT,
    }
    if daily_output_contains(output, "source_recollection_profile"):
        summary["profile_artifact"] = SOURCE_RECOLLECTION_PROFILE_ARTIFACT
    if daily_output_contains(output, "source_recollection_execution_plan"):
        summary["plan_artifact"] = SOURCE_RECOLLECTION_EXECUTION_PLAN_ARTIFACT

    assessment = daily_output_value(output, "source_recollection_quality_assessment")
    if assessment is not None:
        summary["quality"] = source_recollection_quality_manifest_summary(assessment)
    return summary


def source_recollection_quality_manifest_summary(assessment: Any) -> dict[str, Any]:
    return {
        "decision": _field_value(assessment, "decision"),
        "severity": _field_value(assessment, "severity"),
        "route": _field_value(assessment, "route"),
        "recommended_action": _field_value(assessment, "recommended_action"),
        "artifact": SOURCE_RECOLLECTION_QUALITY_ASSESSMENT_ARTIFACT,
    }


def _field_value(value: Any, field_name: str) -> Any:
    if hasattr(value, field_name):
        return getattr(value, field_name)
    if isinstance(value, dict):
        return value.get(field_name)
    return None


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "SOURCE_RECOLLECTION_EXECUTION_PLAN_ARTIFACT",
    "SOURCE_RECOLLECTION_EXECUTION_REPORT_ARTIFACT",
    "SOURCE_RECOLLECTION_PROFILE_ARTIFACT",
    "SOURCE_RECOLLECTION_QUALITY_ASSESSMENT_ARTIFACT",
    "source_recollection_manifest_summary",
    "source_recollection_quality_manifest_summary",
]
