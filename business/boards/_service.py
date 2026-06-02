from __future__ import annotations

from typing import Any

from business.boards.application import BoardServiceRuntime
from business.foundation import (
    AnalysisContext,
    BoardRegistry,
    BoardRunResult,
    BoardType,
    BusinessFeedbackEvent,
    BusinessPolicySnapshot,
    BusinessQualitySnapshot,
    Report,
    Signal,
)
from business.layers.analysis import AnalysisPipeline, AnalysisResult
from business.layers.extraction import ExtractionPipeline, ExtractionResult
from business.layers.output import BoardOutput, BoardOutputPipeline
from business.layers.relation import RelationPipeline, RelationPipelineResult


class BoardServiceBase:
    board_type: BoardType

    def __init__(
        self,
        *,
        board_registry: BoardRegistry | None = None,
        extraction_pipeline: ExtractionPipeline | None = None,
        relation_pipeline: RelationPipeline | None = None,
        analysis_pipeline: AnalysisPipeline | None = None,
        output_pipeline: BoardOutputPipeline | None = None,
    ) -> None:
        self.runtime = BoardServiceRuntime.build(
            board_type=self.board_type,
            board_registry=board_registry,
            extraction_pipeline=extraction_pipeline,
            relation_pipeline=relation_pipeline,
            analysis_pipeline=analysis_pipeline,
            output_pipeline=output_pipeline,
        )
        self.board_registry = self.runtime.board_registry
        self.board_definition = self.runtime.board_definition
        self.extraction_pipeline = self.runtime.extraction_pipeline
        self.relation_pipeline = self.runtime.relation_pipeline
        self.analysis_pipeline = self.runtime.analysis_pipeline
        self.output_pipeline = self.runtime.output_pipeline
        self.signal_pipeline = self.runtime.signal_pipeline
        self.policy_loader = self.runtime.policy_loader
        self.selection_service = self.runtime.selection_service
        self.output_annotation_service = self.runtime.output_annotation_service
        self.pipeline_runner = self.runtime.pipeline_runner
        self.quality_service = self.runtime.quality_service
        self.reference_service = self.runtime.reference_service
        self.report_descriptor_service = self.runtime.report_descriptor_service
        self.report_service = self.runtime.report_service
        self.result_builder = self.runtime.result_builder
        self.run_build_service = self.runtime.run_build_service

    def build_board_output(
        self,
        signals: list[Signal],
        *,
        context: AnalysisContext | None = None,
    ) -> BoardOutput:
        resolved_context = self.run_build_service.resolve_context(context)
        pipeline_run = self.run_build_service.build_output_run(
            signals,
            context=resolved_context,
            report_title=self._report_title(),
            report_summary=self._report_summary(),
            output_postprocessor=self._postprocess_board_output,
        )
        return pipeline_run.output

    def build_report(
        self,
        signals: list[Signal],
        *,
        context: AnalysisContext | None = None,
    ) -> Report:
        output = self.build_board_output(signals, context=context)
        return self.report_service.require_report(output)

    def build_board_run_result(
        self,
        signals: list[Signal],
        *,
        context: AnalysisContext | None = None,
    ) -> BoardRunResult:
        resolved_context = self.run_build_service.resolve_context(context)
        pipeline_run = self.run_build_service.build_output_run(
            signals,
            context=resolved_context,
            report_title=self._report_title(),
            report_summary=self._report_summary(),
            output_postprocessor=self._postprocess_board_output,
        )
        result = self.run_build_service.build_run_result(
            pipeline_run,
            context=resolved_context,
            run_result_postprocessor=self._postprocess_run_result,
        )
        return self.apply_board_specific_policy(result)

    def _run_pipeline_for_selected_signals(
        self,
        selected_signals: list[Signal],
        *,
        context: AnalysisContext,
    ) -> tuple[list[ExtractionResult], RelationPipelineResult, AnalysisResult, BoardOutput]:
        pipeline_run = self.run_build_service.run_selected(
            selected_signals,
            context=context,
            report_title=self._report_title(),
            report_summary=self._report_summary(),
            output_postprocessor=self._postprocess_board_output,
        )
        return (
            pipeline_run.extraction_results,
            pipeline_run.relation_result,
            pipeline_run.analysis,
            pipeline_run.output,
        )

    def _build_base_board_run_result(
        self,
        *,
        output: BoardOutput,
        context: AnalysisContext,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relation_result: RelationPipelineResult,
        analysis: AnalysisResult,
    ) -> BoardRunResult:
        return self.run_build_service.build_run_result_from_parts(
            output=output,
            context=context,
            signals=signals,
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
            run_result_postprocessor=self._postprocess_run_result,
        )

    def apply_board_specific_policy(self, result: BoardRunResult) -> BoardRunResult:
        return result

    def _run_pipeline_for_output(
        self,
        signals: list[Any],
        *,
        context: AnalysisContext,
    ) -> tuple[list[Signal], list[ExtractionResult], RelationPipelineResult, AnalysisResult, BoardOutput]:
        pipeline_run = self.run_build_service.build_output_run(
            signals,
            context=context,
            report_title=self._report_title(),
            report_summary=self._report_summary(),
            output_postprocessor=self._postprocess_board_output,
        )
        return (
            pipeline_run.selected_signals,
            pipeline_run.extraction_results,
            pipeline_run.relation_result,
            pipeline_run.analysis,
            pipeline_run.output,
        )

    def _postprocess_board_output(
        self,
        output: BoardOutput,
        *,
        context: AnalysisContext,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relation_result: RelationPipelineResult,
        analysis: AnalysisResult,
    ) -> BoardOutput:
        return output

    def _postprocess_run_result(
        self,
        result: BoardRunResult,
        *,
        output: BoardOutput,
        context: AnalysisContext,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relation_result: RelationPipelineResult,
        analysis: AnalysisResult,
    ) -> BoardRunResult:
        return result

    def _resolve_context(self, context: AnalysisContext | None) -> AnalysisContext:
        return self.run_build_service.resolve_context(context)

    def _select_signals(self, signals: list[Any], *, context: AnalysisContext) -> list[Signal]:
        return self.run_build_service.select_signals(signals, context=context)

    def select_signals(self, signals: list[Any], *, context: AnalysisContext) -> list[Signal]:
        return self.run_build_service.select_signals(signals, context=context)

    def _report_title(self) -> str:
        return self.report_descriptor_service.build(self.board_definition).title

    def _report_summary(self) -> str:
        return self.report_descriptor_service.build(self.board_definition).summary

    def _quality_summary(self, output: BoardOutput) -> BusinessQualitySnapshot:
        return self.quality_service.build_summary(output)

    def _feedback_candidates(
        self,
        output: BoardOutput,
        quality_summary: BusinessQualitySnapshot,
        policy_snapshot: BusinessPolicySnapshot,
    ) -> list[BusinessFeedbackEvent]:
        return self.quality_service.feedback_candidates(output, quality_summary, policy_snapshot)
