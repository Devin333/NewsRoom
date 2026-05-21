from __future__ import annotations

from business.boards.cross_board.insight_ranker import CrossBoardInsightRanker
from tests.business.boards.cross_board._fixtures import complete_relations, path_result


def test_insight_ranker_preserves_path_scoring_metadata() -> None:
    path = path_result(complete_relations()).paths[0]

    candidates = CrossBoardInsightRanker().rank([path])

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.score == path.path_score
    assert candidate.metadata["scoring_recipe_id"] == "cross_board_path_scoring_v1"
    assert candidate.metadata["scoring_result"]["target_id"] == path.path_id


def test_blocked_path_is_not_promoted_to_insight_candidate() -> None:
    relations = complete_relations()
    relations[2] = relations[2].model_copy(update={"metadata": {"contradictory_evidence": True}})
    blocked_path = path_result(relations).paths[0]

    candidates = CrossBoardInsightRanker().rank([blocked_path])

    assert blocked_path.metadata["scoring_blocked"] is True
    assert candidates == []
