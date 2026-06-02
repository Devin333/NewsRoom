from __future__ import annotations

from typing import Any

from business.boards.services import (
    BoardOutputAnnotationService,
    BoardPipelineRunner,
    BoardQualityService,
    BoardReportExtractionService,
    BoardRunBuildService,
    BoardRunReferenceService,
    BoardRunResultBuilder,
    BoardSignalSelectionService,
)
from business.foundation import (
    AnalysisContext,
    BoardRegistry,
    BoardRunResult,
    BoardType,
    BusinessFeedbackEvent,
    BusinessPolicySnapshot,
    BusinessQualitySnapshot,
    PolicyLoader,
    Report,
    Signal,
)
from business.foundation.registry import default_board_registry
from business.layers.analysis import AnalysisPipeline, AnalysisResult
from business.layers.extraction import ExtractionPipeline, ExtractionResult
from business.layers.output import BoardOutput, BoardOutputPipeline
from business.layers.relation import RelationPipeline, RelationPipelineResult
from business.layers.signal import SignalPipeline


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
        self.board_registry = board_registry or default_board_registry()
        self.board_definition = self.board_registry.get(self.board_type)
        self.extraction_pipeline = extraction_pipeline or ExtractionPipeline()
        self.relation_pipeline = relation_pipeline or RelationPipeline()
        self.analysis_pipeline = analysis_pipeline or AnalysisPipeline()
        self.output_pipeline = output_pipeline or BoardOutputPipeline()
        self.signal_pipeline = SignalPipeline()
        self.policy_loader = PolicyLoader()
        self.selection_service = BoardSignalSelectionService(
            board_type=self.board_type,
            board_definition=self.board_definition,
            signal_pipeline=self.signal_pipeline,
        )
        self.output_annotation_service = BoardOutputAnnotationService()
        self.pipeline_runner = BoardPipelineRunner(
            board_type=self.board_type,
            board_definition=self.board_definition,
            extraction_pipeline=self.extraction_pipeline,
            relation_pipeline=self.relation_pipeline,
            analysis_pipeline=self.analysis_pipeline,
            output_pipeline=self.output_pipeline,
            annotation_service=self.output_annotation_service,
        )
        self.quality_service = BoardQualityService()
        self.reference_service = BoardRunReferenceService()
        self.report_service = BoardReportExtractionService()
        self.result_builder = BoardRunResultBuilder(
            board_type=self.board_type,
            policy_loader=self.policy_loader,
            quality_service=self.quality_service,
            reference_service=self.reference_service,
            report_service=self.report_service,
        )
        self.run_build_service = BoardRunBuildService(
            board_type=self.board_type,
            selection_service=self.selection_service,
            pipeline_runner=self.pipeline_runner,
            result_builder=self.result_builder,
        )

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
        return f"{self.board_definition.name} Report"

    def _report_summary(self) -> str:
        description = self.board_definition.description or self.board_definition.name
        return f"{description} generated from normalized signals."

    def _quality_summary(self, output: BoardOutput) -> BusinessQualitySnapshot:
        return self.quality_service.build_summary(output)

    def _feedback_candidates(
        self,
        output: BoardOutput,
        quality_summary: BusinessQualitySnapshot,
        policy_snapshot: BusinessPolicySnapshot,
    ) -> list[BusinessFeedbackEvent]:
        return self.quality_service.feedback_candidates(output, quality_summary, policy_snapshot)
