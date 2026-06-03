from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from business.boards.cross_board.workflows.daily_intelligence.artifact_sections import (
    publish_daily_artifact_sections,
)
from business.boards.cross_board.workflows.daily_intelligence.agentic_artifact_projection import (
    project_daily_agentic_artifacts,
)
from business.boards.cross_board.workflows.daily_intelligence.evidence_artifact_projection import (
    project_daily_evidence_artifacts,
)
from business.boards.cross_board.workflows.daily_intelligence.output_projection import (
    daily_output_contains as _output_contains,
    daily_output_value as _output_value,
    project_daily_output_for_report_artifacts,
)
from business.boards.cross_board.workflows.daily_intelligence.quality_artifact_projection import (
    quality_manifest_fields,
)
from business.boards.cross_board.workflows.daily_intelligence.source_diagnostic_artifact_projection import (
    project_daily_source_diagnostic_artifacts,
    source_diagnostic_manifest_fields,
)
from business.layers.signal.source_artifact_publication import (
    SOURCE_ARTIFACT_INDEX_KEY,
    SOURCE_ARTIFACT_INDEX_PATH,
    SourceArtifactPublicationService,
)
from framework.workflow.runtime.artifact_publishers import (
    ArtifactPublishContext,
    ArtifactPublishPhase,
    register_manifest_artifact_once,
)
from infrastructure.storage.artifacts import ArtifactRef


AGENTIC_WORKFLOW_IDS = {"daily-intelligence-agentic"}


class DailyIntelligenceArtifactPublisher:
    publisher_id = "daily_intelligence"

    def supports(self, context: ArtifactPublishContext) -> bool:
        if context.phase != ArtifactPublishPhase.TERMINAL:
            return False
        return _is_daily_workflow_id(context.workflow.workflow_id)

    def publish(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        return publish_daily_artifact_sections(
            context,
            source_diagnostics=self._publish_source_diagnostics,
            evidence=self._publish_evidence_artifacts,
            quality=self._publish_quality_artifacts,
            agentic=self._publish_agentic_artifacts,
            report=self._publish_report_artifacts,
        )

    def _publish_evidence_artifacts(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        for artifact in project_daily_evidence_artifacts(context.output):
            refs.append(
                _write_json_artifact(
                    context,
                    artifact.artifact_key,
                    artifact.relative_path,
                    artifact.payload,
                )
            )
        return refs

    def _publish_quality_artifacts(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        output = context.output
        if _output_contains(output, "citation_check_result"):
            citation_check = _output_value(output, "citation_check_result")
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
        context.manifest.update(quality_manifest_fields(output))
        return refs

    def _publish_agentic_artifacts(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        if not _is_agentic_workflow_id(context.workflow.workflow_id):
            return []

        refs: list[ArtifactRef] = []
        projection = project_daily_agentic_artifacts(
            run_id=context.run_id,
            workflow_id=context.workflow.workflow_id,
            workflow_version=context.workflow.version,
            output=context.output,
        )
        for artifact in projection.artifacts:
            refs.append(
                _write_json_artifact(
                    context,
                    artifact.artifact_key,
                    artifact.relative_path,
                    artifact.payload,
                )
            )
        context.manifest.update(projection.manifest_fields)
        return refs

    def _publish_report_artifacts(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        report_output = project_daily_output_for_report_artifacts(context.output)
        if "final_report" in report_output:
            refs.append(
                _write_json_artifact(
                    context,
                    "report_json",
                    "report.json",
                    report_output["final_report"],
                )
            )
        report_markdown = report_output.get("report_markdown")
        if isinstance(report_markdown, str):
            refs.append(
                _write_text_artifact(
                    context,
                    "report_markdown",
                    "report.md",
                    report_markdown,
                    content_type="text/markdown",
                )
            )
        if "blocked_report" in report_output:
            refs.append(
                _write_json_artifact(
                    context,
                    "blocked_report",
                    "blocked_report.json",
                    report_output["blocked_report"],
                )
            )
        return refs

    def _publish_source_diagnostics(self, context: ArtifactPublishContext) -> list[ArtifactRef]:
        refs: list[ArtifactRef] = []
        for artifact in project_daily_source_diagnostic_artifacts(context.output):
            refs.append(
                _write_json_artifact(
                    context,
                    artifact.artifact_key,
                    artifact.relative_path,
                    artifact.payload,
                )
            )
        output = context.output
        context.manifest.update(source_diagnostic_manifest_fields(output))
        source_artifacts = SourceArtifactPublicationService(
            context.artifact_manager
        ).publish(
            context.run_id,
            raw_items=_output_value(output, "raw_items"),
            source_fetch_requests=_output_value(output, "source_fetch_requests"),
            source_fetch_results=_output_value(output, "source_fetch_results"),
            source_errors=_output_value(output, "source_errors"),
        )
        if source_artifacts:
            refs.append(
                _register_existing_artifact(
                    context,
                    SOURCE_ARTIFACT_INDEX_KEY,
                    SOURCE_ARTIFACT_INDEX_PATH,
                    content_type="application/json",
                )
            )
            context.manifest["source_artifacts"] = source_artifacts.manifest_summary
        return refs


def build_daily_intelligence_artifact_publishers() -> list[DailyIntelligenceArtifactPublisher]:
    return [DailyIntelligenceArtifactPublisher()]


def _write_json_artifacts_from_output(
    context: ArtifactPublishContext,
    artifacts: dict[str, str],
) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    for artifact_key, relative_path in artifacts.items():
        if _output_contains(context.output, artifact_key):
            refs.append(
                _write_json_artifact(
                    context,
                    artifact_key,
                    relative_path,
                    _output_value(context.output, artifact_key),
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


def _is_agentic_workflow_id(workflow_id: str) -> bool:
    return str(workflow_id).strip().lower() in AGENTIC_WORKFLOW_IDS
