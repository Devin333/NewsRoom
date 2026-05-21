from __future__ import annotations

from business.foundation import (
    AnalysisContext,
    BoardType,
    Confidence,
    Insight,
    InsightType,
    RadarRecommendation,
    Relation,
    Score,
    Signal,
    TimeWindow,
    build_stable_id,
)
from business.layers.analysis.pipeline import AnalysisResult
from business.layers.extraction.models import ExtractionResult


class InsightBuilder:
    def build_insights(
        self,
        board_type: BoardType,
        signals: list[Signal],
        extraction_results: list[ExtractionResult],
        relations: list[Relation],
        analysis: AnalysisResult,
        context: AnalysisContext,
    ) -> list[Insight]:
        insights: list[Insight] = []
        for radar_item in analysis.radar_items:
            if radar_item.recommendation not in {RadarRecommendation.HIGH_PRIORITY, RadarRecommendation.INVESTIGATE}:
                continue
            insights.append(
                Insight(
                    insight_id=build_stable_id("insight", board_type.value, radar_item.technology_ref.object_id, radar_item.recommendation.value),
                    title=f"{radar_item.name} is worth {radar_item.recommendation.value.replace('_', ' ')}",
                    summary=f"{radar_item.name} shows {radar_item.trend_direction.value} trend and {radar_item.maturity_stage.value} maturity.",
                    insight_type=InsightType.TECHNOLOGY_EMERGENCE,
                    related_object_refs=[radar_item.technology_ref],
                    evidence_relation_ids=list(radar_item.key_relations),
                    time_window=_analysis_time_window(signals, context),
                    confidence=Confidence(value=min(1.0, radar_item.trend_score.value + 0.1), factors=list(radar_item.trend_score.factors)),
                    importance=Score(value=min(1.0, radar_item.impact_score.value), factors=list(radar_item.impact_score.factors)),
                    metadata={
                        "recommendation": radar_item.recommendation.value,
                        "extraction_count": len(extraction_results),
                        "relation_count": len(relations),
                    },
                )
            )
        return insights


def _analysis_time_window(signals: list[Signal], context: AnalysisContext) -> TimeWindow:
    if not signals:
        return context.time_window
    published = [signal.published_at for signal in signals if signal.published_at is not None]
    if not published:
        return context.time_window
    start = min(published)
    end = max(published)
    return TimeWindow(start_at=start, end_at=end, label="board_signals")


__all__ = ["InsightBuilder"]
