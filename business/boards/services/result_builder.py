from __future__ import annotations

from typing import Any

from business.boards.services.quality import BoardQualityService
from business.boards.services.refs import BoardRunReferenceService
from business.foundation import (
    AnalysisContext,
    BoardRunResult,
    BoardType,
    BusinessPolicySnapshot,
    PolicyLoader,
    Report,
    Signal,
    create_policy_snapshot,
)
from business.layers.analysis import AnalysisResult
from business.layers.extraction import ExtractionResult
from business.layers.output import BoardOutput
from business.layers.relation import RelationPipelineResult


class BoardRunResultBuilder:
    def __init__(
        self,
        *,
        board_type: BoardType,
        policy_loader: PolicyLoader,
        quality_service: BoardQualityService | None = None,
        reference_service: BoardRunReferenceService | None = None,
    ) -> None:
        self.board_type = board_type
        self.policy_loader = policy_loader
        self.quality_service = quality_service or BoardQualityService()
        self.reference_service = reference_service or BoardRunReferenceService()

    def build(
        self,
        *,
        output: BoardOutput,
        context: AnalysisContext,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relation_result: RelationPipelineResult,
        analysis: AnalysisResult,
    ) -> BoardRunResult:
        run_id = run_id_from_context(context, self.board_type)
        policy_snapshot = self.policy_snapshot(run_id)
        reports = self.reports_from_output(output)
        quality_summary = self.quality_service.build_summary(output)
        feedback_candidates = self.quality_service.feedback_candidates(output, quality_summary, policy_snapshot)
        refs = self.reference_service.build(
            run_id=run_id,
            board_type=self.board_type,
            context=context,
            signals=signals,
            relations=relation_result.relations,
        )
        snapshot = pipeline_snapshot(
            relation_result=relation_result,
            analysis=analysis,
            extraction_results=extraction_results,
        )
        return BoardRunResult(
            board_type=self.board_type,
            run_id=run_id,
            cards=list(output.cards),
            detail_pages=list(output.detail_pages),
            insights=list(output.insights),
            reports=reports,
            policy_snapshot=policy_snapshot,
            quality_summary=quality_summary,
            feedback_candidates=feedback_candidates,
            trace_ref=refs.trace_ref,
            manifest_ref=refs.manifest_ref,
            artifact_refs=refs.artifact_refs,
            evidence_refs=refs.evidence_refs,
            memory_refs=refs.memory_refs,
            metadata={
                "board_output": output.to_dict(),
                "artifact_refs": [ref.to_dict() for ref in refs.artifact_refs],
                "evidence_refs": [ref.to_dict() for ref in refs.evidence_refs],
                "memory_refs": [ref.to_dict() for ref in refs.memory_refs],
                "pipeline_snapshot": snapshot,
                **legacy_pipeline_metadata(snapshot),
            },
        )

    def policy_snapshot(self, run_id: str) -> BusinessPolicySnapshot:
        return create_policy_snapshot(
            run_id,
            self.policy_loader.active_profiles(board_type=self.board_type),
        )

    def reports_from_output(self, output: BoardOutput) -> list[Report]:
        report_payload = output.metadata.get("report")
        if not isinstance(report_payload, dict):
            return []
        return [Report.model_validate(_report_payload_for_validation(report_payload))]


def run_id_from_context(context: AnalysisContext, board_type: BoardType) -> str:
    run_context = getattr(context, "run_context", None)
    if run_context is not None and getattr(run_context, "run_id", None):
        return str(run_context.run_id)
    return f"{board_type.value}-run"


def pipeline_snapshot(
    *,
    relation_result: RelationPipelineResult,
    analysis: AnalysisResult,
    extraction_results: list[ExtractionResult],
) -> dict[str, Any]:
    return {
        "extraction_count": len(extraction_results),
        "processed_relations": [relation.to_dict() for relation in relation_result.relations],
        "rejected_relations": [rejected.to_dict() for rejected in relation_result.rejected_candidates],
        "analysis": analysis.to_dict(),
    }


def legacy_pipeline_metadata(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "processed_relations": list(snapshot["processed_relations"]),
        "rejected_relations": list(snapshot["rejected_relations"]),
        "analysis": dict(snapshot["analysis"]),
    }


def _report_payload_for_validation(payload: dict[str, object]) -> dict[str, object]:
    cleaned = _drop_serialized_computed_fields(payload)
    if isinstance(cleaned, dict):
        cleaned.pop("board_name", None)
        return cleaned
    return dict(payload)


def _drop_serialized_computed_fields(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _drop_serialized_computed_fields(item)
            for key, item in value.items()
            if key != "level"
        }
    if isinstance(value, list):
        return [_drop_serialized_computed_fields(item) for item in value]
    return value


__all__ = ["BoardRunResultBuilder", "legacy_pipeline_metadata", "pipeline_snapshot", "run_id_from_context"]
