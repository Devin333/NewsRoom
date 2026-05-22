from __future__ import annotations

from typing import Any

from business.boards.cross_board.models import CrossBoardInsight
from business.boards.cross_board.regression_guard import guard_cross_board_insight
from business.boards.cross_board.relation_view_service import RelationViewService
from business.foundation import BusinessQualityCheck, Insight, InsightType, Relation, quality_snapshot_from_checks
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
                (ref for ref in insight.related_object_refs if _object_type_value(ref.object_type) == "technology"),
                None,
            )
            confidence = insight.confidence.value if insight.confidence else 0.0
            duplicate_count = len(evidence) - len(set(evidence))
            guard = guard_cross_board_insight(
                evidence_count=len(evidence),
                board_support_count=len([board for board, ids in board_support.items() if ids]),
                confidence=confidence,
                duplicate_evidence_count=max(0, duplicate_count),
                contradictory_evidence_count=_contradictory_count(relation_views),
                missing_stage_count=_missing_stage_count(relation_views),
            )
            quality = quality_snapshot_from_checks(
                [
                    *guard.checks,
                    BusinessQualityCheck.create(
                        "cross_board_insight_has_primary_technology",
                        passed=primary_technology is not None,
                        severity="warning",
                        reason="Cross-board insight should identify a primary technology.",
                        observed={"has_primary_technology": primary_technology is not None},
                    ),
                ],
                score=1.0 if guard.passed else 0.5,
                confidence=confidence,
            )
            insight_metadata = {
                **dict(insight.metadata),
                "cross_board_guard": guard.to_dict(),
                "board_support": board_support,
                "quality_status": quality.status,
            }
            result.append(
                CrossBoardInsight(
                    insight=insight.model_copy(
                        update={
                            "insight_type": insight.insight_type or InsightType.TECHNOLOGY_EMERGENCE,
                            "metadata": insight_metadata,
                        }
                    ),
                    relation_views=relation_views,
                    primary_technology=primary_technology,
                    board_support=board_support,
                    evidence_refs=list(evidence),
                    guard_result=guard,
                    quality_summary=quality,
                )
            )
        return result


def _contradictory_count(relation_views) -> int:
    relation_types = {view.relation.relation_type.value for view in relation_views}
    return 1 if {"supports", "criticizes"} <= relation_types else 0


def _missing_stage_count(relation_views) -> int:
    seen = {view.relation.relation_type.value for view in relation_views}
    if not seen:
        return 4
    order = ["proposes", "implements", "discusses", "adopts"]
    highest = max((order.index(item) for item in seen if item in order), default=-1)
    if highest < 0:
        return 0
    return len(set(order[: highest + 1]) - seen)


def _object_type_value(value: Any) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)
