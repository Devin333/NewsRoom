from __future__ import annotations

from business.evaluation import (
    contradiction_block_rate,
    cross_board_path_metrics,
    evidence_precision,
    memory_decision_impact,
    memory_hit_rate,
    path_stage_completeness,
)
from tests.business.boards.cross_board._fixtures import complete_relations, path_result


def test_cross_board_path_metrics_capture_completeness_and_evidence() -> None:
    path = path_result(complete_relations()).paths[0]

    assert path_stage_completeness(path) == 1.0
    assert evidence_precision(path) == 1.0
    assert cross_board_path_metrics([path])["path_stage_completeness"] == 1.0


def test_contradiction_block_rate_requires_contradictory_paths_to_be_blocked() -> None:
    relations = complete_relations()
    relations[2] = relations[2].model_copy(update={"metadata": {"contradictory_evidence": True}})
    blocked_path = path_result(relations).paths[0]

    assert blocked_path.contradictory_evidence_count == 1
    assert contradiction_block_rate([blocked_path]) == 1.0


def test_memory_metrics_use_card_metadata_and_decision_features() -> None:
    cards = [
        _Card(memory_used=True, decision=0.8),
        _Card(memory_used=False, decision=None),
    ]

    assert memory_hit_rate(cards) == 0.5
    assert memory_decision_impact(cards) == 0.6


class _Card:
    def __init__(self, *, memory_used: bool, decision: float | None) -> None:
        self.metadata = {"memory_features_used": memory_used}
        self.ranking_features = {}
        if decision is not None:
            self.ranking_features["memory_decision_score"] = decision
