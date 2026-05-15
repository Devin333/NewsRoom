from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from core.framework.artifacts.source_artifacts import SourceArtifactWriter
from core.framework.workflow.artifact_publishers import (
    ArtifactPublishContext,
    ArtifactPublishPhase,
    RuntimeArtifactPublisher,
    WorkflowArtifactPublisherRegistry,
    register_manifest_artifact_once,
)
from storage.artifacts import ArtifactRef


class DailyIntelligenceArtifactPublisher:
    publisher_id = "daily_intelligence"

    def supports(self, context: ArtifactPublishContext) -> bool:
        if context.phase != ArtifactPublishPhase.TERMINAL:
            return False
        return _is_daily_workflow_id(context.workflow.workflow_id)

    def publish(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        refs.extend(self._publish_source_diagnostics(context))
        refs.extend(self._publish_evidence_artifacts(context))
        refs.extend(self._publish_quality_artifacts(context))
        refs.extend(self._publish_report_artifacts(context))
        return refs

    def _publish_evidence_artifacts(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        output = context.output
        if "evidence_bundle" in output:
            refs.append(_write_json_artifact(context, "evidence_bundle", "evidence_bundle.json", output["evidence_bundle"]))
            source_map = output.get("evidence_source_map")
            if source_map is None:
                source_map = _evidence_source_map(output["evidence_bundle"])
            if source_map is not None:
                refs.append(
                    _write_json_artifact(
                        context,
                        "evidence_source_map",
                        "evidence_source_map.json",
                        source_map,
                    )
                )
        elif "evidence_source_map" in output:
            refs.append(
                _write_json_artifact(
                    context,
                    "evidence_source_map",
                    "evidence_source_map.json",
                    output["evidence_source_map"],
                )
            )
        refs.extend(
            _write_json_artifacts_from_output(
                context,
                {
                    "evidence_scores": "evidence_scores.json",
                    "candidate_claims": "candidate_claims.json",
                    "verified_findings": "verified_findings.json",
                },
            )
        )
        return refs

    def _publish_quality_artifacts(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        output = context.output
        if "citation_check_result" in output:
            citation_check = output["citation_check_result"]
            refs.append(
                _write_json_artifact(
                    context,
                    "citation_check_result",
                    "citation_check_result.json",
                    citation_check,
                )
            )
            unsupported_claims = _field_value(citation_check, "unsupported_claims")
            if unsupported_claims:
                refs.append(
                    _write_json_artifact(
                        context,
                        "unsupported_claims",
                        "unsupported_claims.json",
                        unsupported_claims,
                    )
                )
            rejected_claim_usage = _field_value(citation_check, "rejected_claim_usage")
            if rejected_claim_usage:
                refs.append(
                    _write_json_artifact(
                        context,
                        "rejected_claim_usage",
                        "rejected_claim_usage.json",
                        rejected_claim_usage,
                    )
                )

        refs.extend(
            _write_json_artifacts_from_output(
                context,
                {
                    "editor_review": "editor_review.json",
                    "support_matrix": "support_matrix.json",
                    "report_quality_summary": "report_quality_summary.json",
                    "quality_events": "quality_events.json",
                    "quality_gate_metrics": "quality_gate_metrics.json",
                    "quality_result": "quality_result.json",
                    "rewrite_policy": "rewrite_policy.json",
                    "rewrite_instructions": "rewrite_instructions.json",
                    "rewritten_report_draft": "rewritten_report_draft.json",
                    "human_review_request": "human_review_request.json",
                },
            )
        )
        _update_quality_manifest_fields(context.manifest, output)
        return refs

    def _publish_report_artifacts(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        output = context.output
        if "final_report" in output:
            refs.append(_write_json_artifact(context, "report_json", "report.json", output["final_report"]))
        if isinstance(output.get("report_markdown"), str):
            refs.append(
                _write_text_artifact(
                    context,
                    "report_markdown",
                    "report.md",
                    output["report_markdown"],
                    content_type="text/markdown",
                )
            )
        if "blocked_report" in output:
            refs.append(
                _write_json_artifact(
                    context,
                    "blocked_report",
                    "blocked_report.json",
                    output["blocked_report"],
                )
            )
        return refs

    def _publish_source_diagnostics(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs = _write_json_artifacts_from_output(
            context,
            {
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
            },
        )
        output = context.output
        if "source_events" in output:
            context.manifest["source_event_count"] = len(output["source_events"])
        if "source_quality_scores" in output:
            context.manifest["source_quality_score_count"] = len(output["source_quality_scores"])
        if "source_ranking_scores" in output:
            context.manifest["source_ranking_score_count"] = len(output["source_ranking_scores"])
        source_artifacts = SourceArtifactWriter(context.artifact_manager).write_source_artifacts(
            context.run_id,
            raw_items=output.get("raw_items"),
            source_fetch_requests=output.get("source_fetch_requests"),
            source_fetch_results=output.get("source_fetch_results"),
            source_errors=output.get("source_errors"),
        )
        if source_artifacts:
            refs.append(
                _register_existing_artifact(
                    context,
                    "source_artifacts",
                    "source_artifacts/index.json",
                    content_type="application/json",
                )
            )
            context.manifest["source_artifacts"] = {
                "item_count": source_artifacts["item_count"],
                "error_count": source_artifacts["error_count"],
                "raw_content_count": source_artifacts["raw_content_count"],
                "fetch_request_count": source_artifacts["fetch_request_count"],
                "fetch_result_count": source_artifacts["fetch_result_count"],
                "total_count": len(source_artifacts["entries"]),
            }
            if source_artifacts.get("response_headers_count"):
                context.manifest["source_artifacts"]["response_headers_count"] = source_artifacts[
                    "response_headers_count"
                ]
            if source_artifacts.get("parsed_items_count"):
                context.manifest["source_artifacts"]["parsed_items_count"] = source_artifacts[
                    "parsed_items_count"
                ]
        return refs


def build_daily_intelligence_artifact_publishers() -> WorkflowArtifactPublisherRegistry:
    return WorkflowArtifactPublisherRegistry(
        [DailyIntelligenceArtifactPublisher(), RuntimeArtifactPublisher()]
    )


def _write_json_artifacts_from_output(
    context: ArtifactPublishContext,
    artifacts: dict[str, str],
) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    for artifact_key, relative_path in artifacts.items():
        if artifact_key in context.output:
            refs.append(
                _write_json_artifact(
                    context,
                    artifact_key,
                    relative_path,
                    context.output[artifact_key],
                )
            )
    return refs


def _write_json_artifact(
    context: ArtifactPublishContext,
    artifact_key: str,
    relative_path: str,
    payload: Any,
) -> ArtifactRef:
    register_manifest_artifact_once(context.manifest, artifact_key, relative_path)
    path = context.artifact_manager.write_json(context.run_id, relative_path, payload)
    return _artifact_ref(
        context,
        artifact_id=artifact_key,
        artifact_type=artifact_key,
        relative_path=relative_path,
        path=path,
        content_type="application/json",
    )


def _write_text_artifact(
    context: ArtifactPublishContext,
    artifact_key: str,
    relative_path: str,
    text: str,
    *,
    content_type: str,
) -> ArtifactRef:
    register_manifest_artifact_once(context.manifest, artifact_key, relative_path)
    path = context.artifact_manager.write_text(context.run_id, relative_path, text)
    return _artifact_ref(
        context,
        artifact_id=artifact_key,
        artifact_type=artifact_key,
        relative_path=relative_path,
        path=path,
        content_type=content_type,
    )


def _register_existing_artifact(
    context: ArtifactPublishContext,
    artifact_key: str,
    relative_path: str,
    *,
    content_type: str,
) -> ArtifactRef:
    register_manifest_artifact_once(context.manifest, artifact_key, relative_path)
    path = context.artifact_manager.run_dir(context.run_id) / relative_path
    return _artifact_ref(
        context,
        artifact_id=artifact_key,
        artifact_type=artifact_key,
        relative_path=relative_path,
        path=path,
        content_type=content_type,
    )


def _artifact_ref(
    context: ArtifactPublishContext,
    *,
    artifact_id: str,
    artifact_type: str,
    relative_path: str,
    path: Path,
    content_type: str,
) -> ArtifactRef:
    data = path.read_bytes()
    return ArtifactRef(
        artifact_id=artifact_id,
        run_id=context.run_id,
        artifact_type=artifact_type,
        path=Path(relative_path).as_posix(),
        content_type=content_type,
        size_bytes=len(data),
        checksum=sha256(data).hexdigest(),
        redacted=True,
        metadata={
            "artifact_key": artifact_id,
            "workflow_id": context.workflow.workflow_id,
            "workflow_version": context.workflow.version,
            "phase": context.phase.value,
        },
    )


def _update_quality_manifest_fields(manifest: dict[str, Any], output: dict[str, Any]) -> None:
    if "report_quality_summary" in output:
        summary = output["report_quality_summary"]
        if hasattr(summary, "quality_score"):
            manifest["quality_score"] = summary.quality_score
        elif isinstance(summary, dict):
            manifest["quality_score"] = summary.get("quality_score")
    if "quality_events" in output:
        manifest["quality_event_count"] = len(output["quality_events"])
    quality_result = output.get("quality_result")
    route = _field_value(quality_result, "route")
    if route is None:
        route = output.get("quality_route")
    if route is not None:
        manifest["quality_route"] = route
    decision = _field_value(quality_result, "decision")
    if decision is not None:
        manifest["quality_decision"] = decision


def _evidence_source_map(evidence_bundle: Any) -> dict[str, list[str]] | None:
    if isinstance(evidence_bundle, dict):
        source_map = evidence_bundle.get("source_map")
    else:
        source_map = getattr(evidence_bundle, "source_map", None)
    if source_map is None:
        return None
    return {str(key): list(value) for key, value in source_map.items()}


def _field_value(value: Any, field_name: str) -> Any:
    if hasattr(value, field_name):
        return getattr(value, field_name)
    if isinstance(value, dict):
        return value.get(field_name)
    return None


def _is_daily_workflow_id(workflow_id: str) -> bool:
    normalized = str(workflow_id).strip().lower()
    return normalized in {
        "daily",
        "daily-intelligence",
        "daily_intelligence",
    } or normalized.startswith("daily-intelligence")
