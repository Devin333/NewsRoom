from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    project_daily_output_for_source_diagnostic_artifacts,
)
from business.boards.cross_board.workflows.daily_intelligence.source_recollection_artifact_projection import (
    source_recollection_manifest_summary,
)


@dataclass(frozen=True)
class DailySourceDiagnosticArtifact:
    artifact_key: str
    relative_path: str
    payload: Any


SOURCE_DIAGNOSTIC_ARTIFACT_PATHS = {
    "raw_items": "raw_items.json",
    "source_errors": "source_errors.json",
    "skipped_sources": "skipped_sources.json",
    "failed_sources": "failed_sources.json",
    "source_fetch_requests": "source_fetch_requests.json",
    "source_fetch_results": "source_fetch_results.json",
    "source_health_updates": "source_health_updates.json",
    "source_health_report": "source_health_report.json",
    "source_duplicate_groups": "source_duplicate_groups.json",
    "source_events": "source_events.json",
    "source_pipeline_metrics": "source_pipeline_metrics.json",
    "source_connector_dispatch_report": "source_connector_dispatch_report.json",
    "source_error_policy_report": "source_error_policy_report.json",
    "source_fallback_report": "source_fallback_report.json",
    "source_selection_report": "source_selection_report.json",
    "source_coverage_report": "source_coverage_report.json",
    "source_quality_scores": "source_quality_scores.json",
    "source_quality_summary_report": "source_quality_summary_report.json",
    "source_ranking_scores": "source_ranking_scores.json",
    "source_freshness_report": "source_freshness_report.json",
    "source_traceability_report": "source_traceability_report.json",
    "source_governance_report": "source_governance_report.json",
    "source_recollection_profile": "source_recollection/profile.json",
    "source_recollection_execution_plan": "source_recollection/execution_plan.json",
    "source_recollection_execution_report": "source_recollection/execution_report.json",
    "source_recollection_quality_assessment": (
        "source_recollection/quality_assessment.json"
    ),
}


def project_daily_source_diagnostic_artifacts(
    output: Mapping[str, Any],
) -> list[DailySourceDiagnosticArtifact]:
    source_output = project_daily_output_for_source_diagnostic_artifacts(output)
    artifacts: list[DailySourceDiagnosticArtifact] = []
    for artifact_key, relative_path in SOURCE_DIAGNOSTIC_ARTIFACT_PATHS.items():
        if artifact_key in source_output:
            artifacts.append(
                DailySourceDiagnosticArtifact(
                    artifact_key=artifact_key,
                    relative_path=relative_path,
                    payload=source_output[artifact_key],
                )
            )
    return artifacts


def source_diagnostic_manifest_fields(output: Mapping[str, Any]) -> dict[str, Any]:
    source_output = project_daily_output_for_source_diagnostic_artifacts(output)
    fields: dict[str, Any] = {}
    if "source_events" in source_output:
        fields["source_event_count"] = len(source_output["source_events"])
    if "source_quality_scores" in source_output:
        fields["source_quality_score_count"] = len(
            source_output["source_quality_scores"]
        )
    if "source_ranking_scores" in source_output:
        fields["source_ranking_score_count"] = len(
            source_output["source_ranking_scores"]
        )

    source_recollection = source_recollection_manifest_summary(source_output)
    if source_recollection is not None:
        fields["source_recollection"] = source_recollection
    return fields


__all__ = [
    "DailySourceDiagnosticArtifact",
    "SOURCE_DIAGNOSTIC_ARTIFACT_PATHS",
    "project_daily_source_diagnostic_artifacts",
    "source_diagnostic_manifest_fields",
]
