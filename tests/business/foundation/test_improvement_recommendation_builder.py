from __future__ import annotations

from business.foundation import BusinessQualityCheck, quality_snapshot_from_checks
from business.foundation.feedback import (
    ImprovementRecommendationBuilder,
    LearningSignalRecommendationBuilder,
    QualitySummaryRecommendationBuilder,
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
