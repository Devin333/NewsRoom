from __future__ import annotations

from collections.abc import Callable
from typing import Any

from business.boards.services.pipeline import BoardPipelineRun, BoardPipelineRunner
from business.boards.services.result_builder import BoardRunResultBuilder
from business.boards.services.selection import BoardSignalSelectionService
from business.foundation import AnalysisContext, BoardRunPipelineSnapshot, BoardRunResult, BoardType, Signal
from business.layers.analysis import AnalysisResult
from business.layers.extraction import ExtractionResult
from business.layers.output import BoardOutput
from business.layers.relation import RelationPipelineResult


OutputPostprocessor = Callable[..., BoardOutput]
RunResultPostprocessor = Callable[..., BoardRunResult]


class BoardRunBuildService:
    def __init__(
        self,
        *,
        board_type: BoardType,
        selection_service: BoardSignalSelectionService,
        pipeline_runner: BoardPipelineRunner,
        result_builder: BoardRunResultBuilder,
    ) -> None:
        self.board_type = board_type
        self.selection_service = selection_service
        self.pipeline_runner = pipeline_runner
        self.result_builder = result_builder

    def resolve_context(self, context: AnalysisContext | None) -> AnalysisContext:
        if context is None:
            return AnalysisContext(board_type=self.board_type)
        if context.board_type == self.board_type:
            return context
        return context.for_board(self.board_type)

    def select_signals(self, signals: list[Any], *, context: AnalysisContext) -> list[Signal]:
        return self.selection_service.select(signals, context=context)

    def build_output_run(
        self,
        signals: list[Any],
        *,
        context: AnalysisContext,
        report_title: str,
        report_summary: str,
        output_postprocessor: OutputPostprocessor | None = None,
    ) -> BoardPipelineRun:
        selected_signals = self.select_signals(signals, context=context)
        return self.run_selected(
            selected_signals,
            context=context,
            report_title=report_title,
            report_summary=report_summary,
            output_postprocessor=output_postprocessor,
        )

    def run_selected(
        self,
        selected_signals: list[Signal],
        *,
        context: AnalysisContext,
        report_title: str,
        report_summary: str,
        output_postprocessor: OutputPostprocessor | None = None,
    ) -> BoardPipelineRun:
        return self.pipeline_runner.run_selected(
            selected_signals,
            context=context,
            report_title=report_title,
            report_summary=report_summary,
            output_postprocessor=output_postprocessor,
        )

    def build_run_result(
        self,
        pipeline_run: BoardPipelineRun,
        *,
        context: AnalysisContext,
        run_result_postprocessor: RunResultPostprocessor | None = None,
    ) -> BoardRunResult:
        return self.build_run_result_from_parts(
            output=pipeline_run.output,
            context=context,
            signals=pipeline_run.selected_signals,
            extraction_results=pipeline_run.extraction_results,
            relation_result=pipeline_run.relation_result,
            analysis=pipeline_run.analysis,
            pipeline_snapshot=pipeline_run.pipeline_snapshot,
            run_result_postprocessor=run_result_postprocessor,
        )

    def build_run_result_from_parts(
        self,
        *,
        output: BoardOutput,
        context: AnalysisContext,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relation_result: RelationPipelineResult,
        analysis: AnalysisResult,
        pipeline_snapshot: BoardRunPipelineSnapshot | None = None,
        run_result_postprocessor: RunResultPostprocessor | None = None,
    ) -> BoardRunResult:
        result = self.result_builder.build(
            output=output,
            context=context,
            signals=signals,
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
            pipeline_snapshot=pipeline_snapshot,
        )
        if run_result_postprocessor is None:
            return result
        return run_result_postprocessor(
            result,
            output=output,
            context=context,
            signals=signals,
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
        )


__all__ = ["BoardRunBuildService"]
