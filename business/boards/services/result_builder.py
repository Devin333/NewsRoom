from __future__ import annotations

from typing import Any

from business.boards.services.metadata import BoardRunMetadataBuilder, legacy_pipeline_metadata
from business.boards.services.quality import BoardQualityService
from business.boards.services.refs import BoardRunReferenceService
from business.boards.services.report import BoardReportExtractionService
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
        metadata_builder: BoardRunMetadataBuilder | None = None,
        report_service: BoardReportExtractionService | None = None,
    ) -> None:
        self.board_type = board_type
        self.policy_loader = policy_loader
        self.quality_service = quality_service or BoardQualityService()
        self.reference_service = reference_service or BoardRunReferenceService()
        self.metadata_builder = metadata_builder or BoardRunMetadataBuilder()
        self.report_service = report_service or BoardReportExtractionService()

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
        metadata_payload = self.metadata_builder.build(
            output=output,
            refs=refs,
            pipeline_snapshot=snapshot,
        )
        return BoardRunResult(
            board_type=self.board_type,
            run_id=run_id,
            cards=list(output.cards),
            detail_pages=list(output.detail_pages),
            insights=list(output.insights),
            reports=reports,
            board_output=output.to_dict(),
            policy_snapshot=policy_snapshot,
            quality_summary=quality_summary,
            feedback_candidates=feedback_candidates,
            trace_ref=refs.trace_ref,
            manifest_ref=refs.manifest_ref,
            artifact_refs=refs.artifact_refs,
            evidence_refs=refs.evidence_refs,
            memory_refs=refs.memory_refs,
            metadata=metadata_payload.to_result_metadata(),
        )

    def policy_snapshot(self, run_id: str) -> BusinessPolicySnapshot:
        return create_policy_snapshot(
            run_id,
            self.policy_loader.active_profiles(board_type=self.board_type),
        )

    def reports_from_output(self, output: BoardOutput) -> list[Report]:
        return self.report_service.extract_reports(output)


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


__all__ = ["BoardRunResultBuilder", "legacy_pipeline_metadata", "pipeline_snapshot", "run_id_from_context"]
