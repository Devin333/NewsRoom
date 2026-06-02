from __future__ import annotations

import json

from business.boards.cross_board.weekly_improvement import WeeklyImprovementRecommendationService
from business.boards.cross_board.workflows.weekly_intelligence.weekly_improvement import WeeklyImprovementBuilder


def test_weekly_improvement_builder_creates_recommendations_from_quality() -> None:
    result = WeeklyImprovementBuilder().build(
        {"weak_spots": ["missing_source_urls"]},
        {"weak_signal_trends": []},
    )

    assert result["recommendations"]
    assert result["risks"]
    assert result["recommendations"][0]["target_type"] == "board_quality_gate"
    assert result["policy_experiment_profiles"][0]["target_type"] == "board_quality_gate"
    assert result["policy_experiment_profile_ids"] == [
        result["policy_experiment_profiles"][0]["profile_id"]
    ]


def test_weekly_improvement_builder_uses_policy_experiment_language() -> None:
    result = WeeklyImprovementBuilder().build(
        {"weak_spots": ["missing_source_urls"]},
        {"weak_signal_trends": []},
    )

    serialized = json.dumps(result, sort_keys=True)
    assert "override" not in serialized
    assert "proposed_patch" not in serialized
    assert result["risks"] == ["manual approval required before policy experiment activation"]
    assert result["next_actions"] == ["review weekly policy experiment recommendations"]


def test_weekly_improvement_service_creates_prompt_hint_profile_from_weak_trends() -> None:
    report = WeeklyImprovementRecommendationService().build(
        {"weak_spots": []},
        {"weak_signal_trends": [{"topic": "agent-memory", "confidence": 0.42}]},
    )

    result = report.to_dict()
    assert result["recommendations"][0]["target_type"] == "skill_prompt_hint"
    assert result["policy_experiment_profiles"][0]["target_type"] == "skill_prompt_hint"
    assert result["policy_experiment_profiles"][0]["parameters"]["evidence_count"] == 1
