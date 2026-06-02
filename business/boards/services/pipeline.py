from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from business.boards.services.annotation import BoardOutputAnnotationService
from business.foundation import AnalysisContext, BoardDefinition, BoardRunPipelineSnapshot, BoardType, Signal
from business.layers.analysis import AnalysisPipeline, AnalysisResult
from business.layers.extraction import ExtractionPipeline, ExtractionResult
from business.layers.output import BoardOutput, BoardOutputPipeline
from business.layers.relation import RelationPipeline, RelationPipelineResult


@dataclass(frozen=True)
class BoardPipelineRun:
    selected_signals: list[Signal]
    extraction_results: list[ExtractionResult]
    relation_result: RelationPipelineResult
    analysis: AnalysisResult
    output: BoardOutput
    pipeline_snapshot: BoardRunPipelineSnapshot


class BoardPipelineRunner:
    def __init__(
        self,
        *,
        board_type: BoardType,
        board_definition: BoardDefinition,
        extraction_pipeline: ExtractionPipeline,
        relation_pipeline: RelationPipeline,
        analysis_pipeline: AnalysisPipeline,
        output_pipeline: BoardOutputPipeline,
        annotation_service: BoardOutputAnnotationService | None = None,
    ) -> None:
        self.board_type = board_type
        self.board_definition = board_definition
        self.extraction_pipeline = extraction_pipeline
        self.relation_pipeline = relation_pipeline
        self.analysis_pipeline = analysis_pipeline
        self.output_pipeline = output_pipeline
        self.annotation_service = annotation_service or BoardOutputAnnotationService()

    def run_selected(
        self,
        selected_signals: list[Signal],
        *,
        context: AnalysisContext,
        report_title: str,
        report_summary: str,
        output_postprocessor: Callable[..., BoardOutput] | None = None,
    ) -> BoardPipelineRun:
        extraction_results = self.extraction_pipeline.run(selected_signals, context)
        relation_result = self.relation_pipeline.run(
            selected_signals,
            extraction_results,
            context=context,
        )
        analysis = self.analysis_pipeline.run(
            selected_signals,
            extraction_results,
            relation_result.relations,
            context,
        )
        output = self.output_pipeline.build_board_output(
            self.board_type,
            selected_signals,
            extraction_results,
            relation_result.relations,
            analysis,
            context,
        )
        self.annotation_service.annotate(
            output,
            board_type=self.board_type,
            board_definition=self.board_definition,
            context=context,
            signals=selected_signals,
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
            report_title=report_title,
            report_summary=report_summary,
        )
        if output_postprocessor is not None:
            output = output_postprocessor(
                output,
                context=context,
                signals=selected_signals,
                extraction_results=extraction_results,
                relation_result=relation_result,
                analysis=analysis,
            )
        return BoardPipelineRun(
            selected_signals=list(selected_signals),
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
            output=output,
            pipeline_snapshot=board_pipeline_snapshot(
                extraction_results=extraction_results,
                relation_result=relation_result,
                analysis=analysis,
            ),
        )


def board_pipeline_snapshot(
    *,
    extraction_results: list[ExtractionResult],
    relation_result: RelationPipelineResult,
    analysis: AnalysisResult,
) -> BoardRunPipelineSnapshot:
    return BoardRunPipelineSnapshot(
        extraction_count=len(extraction_results),
        processed_relations=[relation.to_dict() for relation in relation_result.relations],
        rejected_relations=[rejected.to_dict() for rejected in relation_result.rejected_candidates],
        analysis=analysis.to_dict(),
    )


__all__ = ["BoardPipelineRun", "BoardPipelineRunner", "board_pipeline_snapshot"]
