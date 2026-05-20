from __future__ import annotations

from typing import Any

from business.foundation import AnalysisContext, BoardRegistry, BoardType, Report, Signal
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

    def build_board_output(
        self,
        signals: list[Signal],
        *,
        context: AnalysisContext | None = None,
    ) -> BoardOutput:
        resolved_context = self._resolve_context(context)
        selected_signals = self._select_signals(signals, context=resolved_context)
        extraction_results = self.extraction_pipeline.run(selected_signals, resolved_context)
        relation_result = self.relation_pipeline.run(
            selected_signals,
            extraction_results,
            context=resolved_context,
        )
        analysis = self.analysis_pipeline.run(
            selected_signals,
            extraction_results,
            relation_result.relations,
            resolved_context,
        )
        output = self.output_pipeline.build_board_output(
            self.board_type,
            selected_signals,
            extraction_results,
            relation_result.relations,
            analysis,
            resolved_context,
        )
        self._annotate_output(
            output,
            context=resolved_context,
            signals=selected_signals,
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
        )
        return output

    def build_report(
        self,
        signals: list[Signal],
        *,
        context: AnalysisContext | None = None,
    ) -> Report:
        output = self.build_board_output(signals, context=context)
        report_payload = dict(output.metadata.get("report") or {})
        if not report_payload:
            raise ValueError("board output does not include a report payload")
        return Report.model_validate(report_payload)

    def _resolve_context(self, context: AnalysisContext | None) -> AnalysisContext:
        if context is None:
            return AnalysisContext(board_type=self.board_type)
        if context.board_type == self.board_type:
            return context
        return context.for_board(self.board_type)

    def _select_signals(self, signals: list[Any], *, context: AnalysisContext) -> list[Signal]:
        coerced = self.signal_pipeline.coerce_signals(
            list(signals),
            context=context,
            board_type=self.board_type,
        ).signals
        if self.board_type == BoardType.CROSS_BOARD:
            return sorted(coerced, key=_signal_sort_key, reverse=True)
        selected = [
            signal
            for signal in coerced
            if signal.board_type == self.board_type
            or signal.signal_type.value in self.board_definition.signal_types
        ]
        return sorted(selected, key=_signal_sort_key, reverse=True)

    def _annotate_output(
        self,
        output: BoardOutput,
        *,
        context: AnalysisContext,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relation_result: RelationPipelineResult,
        analysis: AnalysisResult,
    ) -> None:
        output.metadata.update(
            {
                "board_type": self.board_type.value,
                "board_name": self.board_definition.name,
                "board_definition": self.board_definition.to_dict(),
                "signal_count": len(signals),
                "selection": {
                    "signal_types": list(self.board_definition.signal_types),
                    "visible_sections": list(self.board_definition.visible_sections),
                },
                "extraction_count": len(extraction_results),
                "relation_count": len(relation_result.relations),
                "rejected_relation_count": len(relation_result.rejected_candidates),
                "analysis_metadata": dict(analysis.metadata),
                "report": {
                    **dict(output.metadata.get("report") or {}),
                    "board_type": self.board_type.value,
                    "board_name": self.board_definition.name,
                    "title": self._report_title(),
                    "summary": self._report_summary(),
                },
                "context": context.to_dict(),
            }
        )

    def _report_title(self) -> str:
        return f"{self.board_definition.name} Report"

    def _report_summary(self) -> str:
        description = self.board_definition.description or self.board_definition.name
        return f"{description} generated from normalized signals."


def _signal_sort_key(signal: Signal) -> tuple[int, str, str]:
    published_at = signal.published_at
    timestamp = int(published_at.timestamp()) if published_at is not None else 0
    return timestamp, signal.signal_id, signal.title
