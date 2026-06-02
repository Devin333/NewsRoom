from __future__ import annotations

from dataclasses import dataclass

from business.boards.domain import BoardQualityService, BoardRunReferenceService, BoardSignalSelectionService
from business.boards.services import (
    BoardOutputAnnotationService,
    BoardPipelineRunner,
    BoardReportDescriptorService,
    BoardReportExtractionService,
    BoardRunBuildService,
    BoardRunResultBuilder,
)
from business.foundation import BoardDefinition, BoardRegistry, BoardType, PolicyLoader
from business.foundation.registry import default_board_registry
from business.layers.analysis import AnalysisPipeline
from business.layers.extraction import ExtractionPipeline
from business.layers.output import BoardOutputPipeline
from business.layers.relation import RelationPipeline
from business.layers.signal import SignalPipeline


@dataclass(frozen=True)
class BoardServiceRuntime:
    board_registry: BoardRegistry
    board_definition: BoardDefinition
    extraction_pipeline: ExtractionPipeline
    relation_pipeline: RelationPipeline
    analysis_pipeline: AnalysisPipeline
    output_pipeline: BoardOutputPipeline
    signal_pipeline: SignalPipeline
    policy_loader: PolicyLoader
    selection_service: BoardSignalSelectionService
    output_annotation_service: BoardOutputAnnotationService
    pipeline_runner: BoardPipelineRunner
    quality_service: BoardQualityService
    reference_service: BoardRunReferenceService
    report_descriptor_service: BoardReportDescriptorService
    report_service: BoardReportExtractionService
    result_builder: BoardRunResultBuilder
    run_build_service: BoardRunBuildService

    @classmethod
    def build(
        cls,
        *,
        board_type: BoardType,
        board_registry: BoardRegistry | None = None,
        extraction_pipeline: ExtractionPipeline | None = None,
        relation_pipeline: RelationPipeline | None = None,
        analysis_pipeline: AnalysisPipeline | None = None,
        output_pipeline: BoardOutputPipeline | None = None,
    ) -> "BoardServiceRuntime":
        resolved_registry = board_registry or default_board_registry()
        board_definition = resolved_registry.get(board_type)
        resolved_extraction = extraction_pipeline or ExtractionPipeline()
        resolved_relation = relation_pipeline or RelationPipeline()
        resolved_analysis = analysis_pipeline or AnalysisPipeline()
        resolved_output = output_pipeline or BoardOutputPipeline()
        signal_pipeline = SignalPipeline()
        policy_loader = PolicyLoader()
        selection_service = BoardSignalSelectionService(
            board_type=board_type,
            board_definition=board_definition,
            signal_pipeline=signal_pipeline,
        )
        annotation_service = BoardOutputAnnotationService()
        pipeline_runner = BoardPipelineRunner(
            board_type=board_type,
            board_definition=board_definition,
            extraction_pipeline=resolved_extraction,
            relation_pipeline=resolved_relation,
            analysis_pipeline=resolved_analysis,
            output_pipeline=resolved_output,
            annotation_service=annotation_service,
        )
        quality_service = BoardQualityService()
        reference_service = BoardRunReferenceService()
        report_descriptor_service = BoardReportDescriptorService()
        report_service = BoardReportExtractionService()
        result_builder = BoardRunResultBuilder(
            board_type=board_type,
            policy_loader=policy_loader,
            quality_service=quality_service,
            reference_service=reference_service,
            report_service=report_service,
        )
        run_build_service = BoardRunBuildService(
            board_type=board_type,
            selection_service=selection_service,
            pipeline_runner=pipeline_runner,
            result_builder=result_builder,
        )
        return cls(
            board_registry=resolved_registry,
            board_definition=board_definition,
            extraction_pipeline=resolved_extraction,
            relation_pipeline=resolved_relation,
            analysis_pipeline=resolved_analysis,
            output_pipeline=resolved_output,
            signal_pipeline=signal_pipeline,
            policy_loader=policy_loader,
            selection_service=selection_service,
            output_annotation_service=annotation_service,
            pipeline_runner=pipeline_runner,
            quality_service=quality_service,
            reference_service=reference_service,
            report_descriptor_service=report_descriptor_service,
            report_service=report_service,
            result_builder=result_builder,
            run_build_service=run_build_service,
        )


__all__ = ["BoardServiceRuntime"]
