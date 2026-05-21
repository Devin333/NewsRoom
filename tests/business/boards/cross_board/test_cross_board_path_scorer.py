from __future__ import annotations

from business.boards.cross_board import CrossBoardPathScoringService
from tests.business.boards.cross_board._fixtures import complete_relations, path_result, relation


def test_cross_board_path_scorer_attaches_runtime_result() -> None:
    path = path_result(complete_relations()).paths[0]
    scored = CrossBoardPathScoringService().score_path(path)

    assert scored.path_score > 0.0
    assert scored.confidence > 0.0
    assert scored.metadata["scoring_recipe_id"] == "cross_board_path_scoring_v1"
    assert scored.metadata["scoring_result"]["recipe_id"] == "cross_board_path_scoring_v1"
    assert scored.metadata["scoring_result"]["score"]["final_score"] == scored.path_score
    assert scored.metadata["scoring_result"]["trace"]["trace_id"] == scored.metadata["scoring_trace_id"]


def test_path_finder_returns_paths_sorted_by_runtime_score() -> None:
    strong = complete_relations(evidence_prefix="strong")
    weak = [relation("proposes", "paper", "paper-2", "weak-paper")]
    weak[0] = weak[0].model_copy(
        update={
            "target_ref": weak[0].target_ref.model_copy(update={"object_id": "tech-weak", "label": "Weak Tech"}),
            "relation_id": "rel-proposes-paper-2",
        }
    )

    paths = path_result([*weak, *strong]).paths

    assert len(paths) == 2
    assert paths[0].path_score >= paths[1].path_score
    assert all("scoring_result" in path.metadata for path in paths)
