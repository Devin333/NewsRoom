from __future__ import annotations

from typing import Any

from business.boards.cross_board.graph_builder import CrossBoardGraphBuilder
from business.boards.cross_board.graph_models import CrossBoardGraphIntelligenceResult
from business.boards.cross_board.graph_quality import CrossBoardGraphQualityEvaluator
from business.boards.cross_board.insight_ranker import CrossBoardInsightRanker
from business.boards.cross_board.path_finder import CrossBoardPathFinder


class CrossBoardGraphIntelligenceService:
    def __init__(
        self,
        *,
        graph_builder: CrossBoardGraphBuilder | None = None,
        path_finder: CrossBoardPathFinder | None = None,
        quality_evaluator: CrossBoardGraphQualityEvaluator | None = None,
        insight_ranker: CrossBoardInsightRanker | None = None,
    ) -> None:
        self.graph_builder = graph_builder or CrossBoardGraphBuilder()
        self.path_finder = path_finder or CrossBoardPathFinder()
        self.quality_evaluator = quality_evaluator or CrossBoardGraphQualityEvaluator()
        self.insight_ranker = insight_ranker or CrossBoardInsightRanker()

    def build_from_processed(
        self,
        *,
        signals: list[Any],
        extraction_results: list[Any],
        relations: list[Any],
        analysis: Any | None = None,
        board_outputs: dict[str, Any] | None = None,
    ) -> CrossBoardGraphIntelligenceResult:
        signal_list = list(signals)
        extraction_result_list = list(extraction_results)
        relation_list = list(relations)
        graph = self.graph_builder.build(
            signals=signal_list,
            extraction_results=extraction_result_list,
            relations=relation_list,
            analysis=analysis,
            board_outputs=board_outputs or {},
        )
        path_result = self.path_finder.find_paths(graph)
        quality_summary = self.quality_evaluator.evaluate(path_result.paths)
        insights = self.insight_ranker.rank(path_result.paths)
        return CrossBoardGraphIntelligenceResult(
            graph=graph,
            paths=path_result.paths,
            insights=insights,
            quality_summary=quality_summary,
            metadata={
                "signal_count": len(signal_list),
                "extraction_result_count": len(extraction_result_list),
                "relation_count": len(relation_list),
                "path_count": len(path_result.paths),
                "insight_count": len(insights),
            },
        )


__all__ = ["CrossBoardGraphIntelligenceService"]
