from __future__ import annotations

from tests.business.boards.cross_board._fixtures import complete_relations, path_result


def test_duplicate_evidence_is_reflected_in_scoring_result() -> None:
    unique_path = path_result(complete_relations()).paths[0]
    duplicate_path = path_result(
        [
            item.model_copy(update={"evidence_signal_ids": ["shared-evidence"]})
            for item in complete_relations(evidence_prefix="shared")
        ]
    ).paths[0]

    assert duplicate_path.duplicate_evidence_count > 0
    assert duplicate_path.metadata["scoring_result"]["warnings"]
    assert duplicate_path.path_score < unique_path.path_score


def test_contradictory_evidence_blocks_runtime_scoring() -> None:
    relations = complete_relations()
    relations[2] = relations[2].model_copy(update={"metadata": {"contradictory_evidence": True}})
    path = path_result(relations).paths[0]

    scoring_result = path.metadata["scoring_result"]

    assert path.contradictory_evidence_count == 1
    assert scoring_result["blocked"] is True
    assert path.path_score == 0.0
    assert "contradiction detected" in path.blocking_reasons
