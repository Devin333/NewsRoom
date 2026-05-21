from __future__ import annotations

from business.boards.cross_board.graph_models import CrossBoardEvidenceChain, CrossBoardPath
from business.foundation import ObjectRef, ObjectType
from business.scoring import (
    cross_board_path_feature_vector,
    cross_board_path_features,
    cross_board_path_scoring_recipe,
    cross_board_path_scoring_target,
)
from framework.scoring import ScoringRuntime


def test_cross_board_path_adapter_and_recipe_score_path() -> None:
    path = CrossBoardPath(
        path_id="path-1",
        technology_ref=ObjectRef(object_type=ObjectType.TECHNOLOGY, object_id="tech-1"),
        board_sequence=["ai_news", "paper_radar", "project_radar"],
        confidence=0.8,
        path_score=0.7,
        missing_stage_types=[],
        duplicate_evidence_count=0,
        contradictory_evidence_count=0,
        evidence_relation_ids=["r1", "r2", "r3"],
        evidence_chain=CrossBoardEvidenceChain(
            chain_id="chain-1",
            evidence_count=3,
            board_support_count=3,
            min_relation_confidence=0.7,
            average_relation_confidence=0.8,
            duplicate_evidence_count=0,
            contradictory_evidence_count=0,
            missing_stage_count=0,
        ),
    )

    features = cross_board_path_features(path)
    vector = cross_board_path_feature_vector(path)
    target = cross_board_path_scoring_target(path)
    recipe = cross_board_path_scoring_recipe()
    result = ScoringRuntime().score_path(target, features=vector, recipe=recipe)

    assert features["stage_completeness"] == 1.0
    assert target.target_type == "cross_board_path"
    assert result.final_score > 0.0
