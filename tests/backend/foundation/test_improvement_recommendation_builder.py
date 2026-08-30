from __future__ import annotations

from backend.foundation import BusinessQualityCheck, quality_snapshot_from_checks
from backend.foundation.feedback import (
    ImprovementRecommendationBuilder,
    LearningSignalRecommendationBuilder,
    QualitySummaryRecommendationBuilder,
    dedupe_recommendations,
    ImprovementRecommendation,
)


def test_learning_signal_recommendation_builder_maps_signal_payload() -> None:
    recommendation = LearningSignalRecommendationBuilder().build(
        [
            {
                "signal_id": "signal-1",
                "signal_type": "ranking_duplicate_evidence",
                "target_layer": "cross_board_graph",
                "suggested_policy_profile_id": "cross-board-policy",
                "related_feedback_ids": ["feedback-1"],
                "frequency": 3,
                "severity_score": 0.85,
                "description": "Duplicate evidence affects cross-board ranking.",
            }
        ],
        board_type="cross_board",
    )[0]

    assert recommendation.source == "learning_signal"
    assert recommendation.target_type == "ranking_weight"
    assert recommendation.target_id == "cross-board-policy"
    assert recommendation.severity == "error"
    assert recommendation.suggested_action == "tighten duplicate threshold"
    assert recommendation.evidence[0]["frequency"] == 3


def test_quality_summary_recommendation_builder_uses_failed_checks_only() -> None:
    quality = quality_snapshot_from_checks(
        [
            BusinessQualityCheck.create(
                "cards_have_evidence",
                passed=False,
                severity="error",
                reason="Cards need evidence.",
                observed={"missing": 2},
            ),
            BusinessQualityCheck.create("cards_have_titles", passed=True),
        ]
    )

    recommendations = QualitySummaryRecommendationBuilder().build(quality, board_type="ai_news")

    assert len(recommendations) == 1
    assert recommendations[0].source == "quality_summary"
    assert recommendations[0].target_type == "board_quality_gate"
    assert recommendations[0].target_id == "cards_have_evidence"
    assert recommendations[0].severity == "error"


def test_improvement_recommendation_builder_delegates_to_source_builders() -> None:
    builder = ImprovementRecommendationBuilder()

    learning_recommendations = builder.build_from_learning_signals(
        [{"signal_type": "source_reliability", "severity_score": 0.5}],
        board_type="ai_news",
    )
    quality_recommendations = builder.build_from_quality_summary(
        {"checks": [{"check_type": "board_gate", "passed": False}]},
        board_type="ai_news",
    )

    assert learning_recommendations[0].source == "learning_signal"
    assert quality_recommendations[0].source == "quality_summary"


def test_improvement_recommendation_builder_builds_and_dedupes_sources() -> None:
    recommendation = _recommendation("rec-1", source="learning_signal")
    builder = ImprovementRecommendationBuilder(
        learning_signal_builder=_StaticRecommendationBuilder([recommendation]),
        quality_summary_builder=_StaticRecommendationBuilder([_recommendation("rec-1", source="quality_summary")]),
    )

    recommendations = builder.build([{"signal_type": "x"}], board_type="ai_news", quality_summary={"checks": []})

    assert recommendations == [recommendation]


def test_dedupe_recommendations_preserves_first_seen_order() -> None:
    first = _recommendation("rec-1", source="learning_signal")
    second = _recommendation("rec-2", source="quality_summary")
    duplicate = _recommendation("rec-1", source="quality_summary")

    assert dedupe_recommendations([first, second, duplicate]) == [first, second]


class _StaticRecommendationBuilder:
    def __init__(self, recommendations: list[ImprovementRecommendation]) -> None:
        self.recommendations = recommendations

    def build(self, *_args, **_kwargs) -> list[ImprovementRecommendation]:
        return list(self.recommendations)


def _recommendation(recommendation_id: str, *, source: str) -> ImprovementRecommendation:
    return ImprovementRecommendation(
        recommendation_id=recommendation_id,
        source=source,
        board_type="ai_news",
        target_type="policy_threshold",
        target_id="threshold",
        severity="warning",
        reason="review threshold",
        suggested_action="review policy threshold",
    )
