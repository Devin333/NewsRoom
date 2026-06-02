from __future__ import annotations

from business.boards.application.result import BoardRunApplicationResultBuilder, run_id_from_context
from business.boards.services.metadata import BoardRunMetadataBuilder, legacy_pipeline_metadata
from business.boards.services.pipeline import board_pipeline_snapshot
from business.boards.services.quality import BoardQualityService
from business.boards.services.refs import BoardRunReferenceService
from business.boards.services.report import BoardReportExtractionService
from business.foundation import (
    AnalysisContext,
    BoardRunPipelineSnapshot,
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
        self.application_result_builder = BoardRunApplicationResultBuilder(
            board_type=board_type,
            policy_loader=policy_loader,
            quality_service=self.quality_service,
            reference_service=self.reference_service,
            report_service=self.report_service,
        )

    def build(
        self,
        *,
        output: BoardOutput,
        context: AnalysisContext,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relation_result: RelationPipelineResult,
        analysis: AnalysisResult,
        pipeline_snapshot: BoardRunPipelineSnapshot | None = None,
    ) -> BoardRunResult:
        snapshot = pipeline_snapshot or board_pipeline_snapshot(
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
        )
        application_result = self.application_result_builder.build(
            output=output,
            pipeline_snapshot=snapshot,
            context=context,
            signals=signals,
            relations=relation_result.relations,
        )
        metadata_payload = self.metadata_builder.build(
            application_result=application_result,
        )
        return application_result.to_board_run_result(metadata=metadata_payload.to_result_metadata())

    def policy_snapshot(self, run_id: str) -> BusinessPolicySnapshot:
        return create_policy_snapshot(
            run_id,
            self.policy_loader.active_profiles(board_type=self.board_type),
        )

    def reports_from_output(self, output: BoardOutput) -> list[Report]:
        return self.report_service.extract_reports(output)


def pipeline_snapshot(
    *,
    relation_result: RelationPipelineResult,
    analysis: AnalysisResult,
    extraction_results: list[ExtractionResult],
) -> BoardRunPipelineSnapshot:
    return board_pipeline_snapshot(
        extraction_results=extraction_results,
        relation_result=relation_result,
        analysis=analysis,
    )


__all__ = ["BoardRunResultBuilder", "legacy_pipeline_metadata", "pipeline_snapshot", "run_id_from_context"]
