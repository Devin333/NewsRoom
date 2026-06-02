from __future__ import annotations

from business.boards._service import BoardServiceBase
from business.boards.cross_board.graph_models import CrossBoardGraphIntelligenceResult
from business.boards.cross_board.graph_intelligence_service import CrossBoardGraphIntelligenceService
from business.boards.cross_board.insight_service import CrossBoardInsightService
from business.boards.cross_board.run_result_enricher import CrossBoardRunResultEnricher
from business.foundation import BoardType


class CrossBoardService(BoardServiceBase):
    board_type = BoardType.CROSS_BOARD

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cross_board_insight_service = CrossBoardInsightService()
        self.graph_intelligence_service = CrossBoardGraphIntelligenceService()
        self.run_result_enricher = CrossBoardRunResultEnricher()

    def build_board_run_result(self, signals, *, context=None):
        resolved_context = self._resolve_context(context)
        selected_signals, extraction_results, relation_result, analysis, output = self._run_pipeline_for_output(
            signals,
            context=resolved_context,
        )
        result = self._build_base_board_run_result(
            output=output,
            context=resolved_context,
            signals=selected_signals,
            extraction_results=extraction_results,
            relation_result=relation_result,
            analysis=analysis,
        )
        cross_insights = self.cross_board_insight_service.build_insights(
            result.insights,
            relation_result.relations,
            analysis=analysis,
        )
        graph_result = self.build_graph_intelligence_from_processed(
            signals=selected_signals,
            extraction_results=extraction_results,
            relations=relation_result.relations,
            analysis=analysis,
            board_outputs={self.board_type.value: output},
        )
        return self.run_result_enricher.attach(result, cross_insights, graph_result)

    def build_graph_intelligence(self, signals, *, context=None, board_outputs=None) -> CrossBoardGraphIntelligenceResult:
        resolved_context = self._resolve_context(context)
        selected_signals, extraction_results, relation_result, analysis, output = self._run_pipeline_for_output(
            signals,
            context=resolved_context,
        )
        outputs = dict(board_outputs or {})
        outputs.setdefault(self.board_type.value, output)
        return self.build_graph_intelligence_from_processed(
            signals=selected_signals,
            extraction_results=extraction_results,
            relations=relation_result.relations,
            analysis=analysis,
            board_outputs=outputs,
        )

    def build_graph_intelligence_from_processed(
        self,
        *,
        signals,
        extraction_results,
        relations,
        analysis=None,
        board_outputs=None,
    ) -> CrossBoardGraphIntelligenceResult:
        return self.graph_intelligence_service.build_from_processed(
            signals=signals,
            extraction_results=extraction_results,
            relations=relations,
            analysis=analysis,
            board_outputs=board_outputs,
        )
