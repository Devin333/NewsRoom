from __future__ import annotations

from business.boards.cross_board.models import CrossBoardInsight
from business.boards.cross_board.relation_view_service import RelationViewService
from business.foundation import Insight, InsightType, Relation
from business.layers.analysis import AnalysisResult


class CrossBoardInsightService:
    def build_insights(self, insights: list[Insight], relations: list[Relation], analysis: AnalysisResult | None = None) -> list[CrossBoardInsight]:
        views = RelationViewService().build_views(relations)
        result: list[CrossBoardInsight] = []
        for insight in insights:
            evidence = set(insight.evidence_relation_ids)
            relation_views = [view for view in views if view.relation.relation_id in evidence]
            board_support: dict[str, list[str]] = {}
            for view in relation_views:
                board_support.setdefault(view.source_board.value, []).append(view.relation.relation_id)
                board_support.setdefault(view.target_board.value, []).append(view.relation.relation_id)
            primary_technology = next(
                (ref for ref in insight.related_object_refs if ref.object_type.value == "technology"),
                None,
            )
            result.append(
                CrossBoardInsight(
                    insight=insight.model_copy(update={"insight_type": insight.insight_type or InsightType.TECHNOLOGY_EMERGENCE}),
                    relation_views=relation_views,
                    primary_technology=primary_technology,
                    board_support=board_support,
                    evidence_refs=list(evidence),
                )
            )
        return result
