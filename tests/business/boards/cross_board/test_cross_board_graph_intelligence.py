from __future__ import annotations

from business.boards.cross_board import CrossBoardGraphBuilder, CrossBoardPathFinder
from business.foundation import Confidence, ObjectRef, Relation, RelationType


def test_complete_cross_board_chain_generates_high_quality_path() -> None:
    result = _path_result(_relations())
    path = result.paths[0]

    assert path.board_sequence == ["paper_radar", "project_radar", "community_pulse", "ai_news"]
    assert path.confidence > 0
    assert path.path_score > 0
    assert not path.missing_stage_types
    assert path.guard_result is not None
    assert path.guard_result.passed


def test_missing_stage_produces_blocking_guard() -> None:
    result = _path_result([_relation("proposes", "paper", "paper-1", "ev-paper")])
    path = result.paths[0]

    assert "project_implementation" in path.missing_stage_types
    assert path.guard_result is not None
    assert not path.guard_result.passed
    assert path.blocking_reasons


def test_contradictory_evidence_blocks_path() -> None:
    relations = _relations()
    relations[2] = relations[2].model_copy(update={"metadata": {"contradictory_evidence": True}})
    path = _path_result(relations).paths[0]

    assert path.contradictory_evidence_count == 1
    assert path.guard_result is not None
    assert not path.guard_result.passed
    assert any("Contradictory evidence" in reason for reason in path.blocking_reasons)


def test_duplicate_evidence_does_not_inflate_score() -> None:
    unique_path = _path_result(_relations()).paths[0]
    duplicate_path = _path_result(
        [
            _relation("proposes", "paper", "paper-1", "ev-shared"),
            _relation("implements", "project", "project-1", "ev-shared"),
            _relation("discusses", "community_thread", "thread-1", "ev-shared"),
            _relation("adopts", "news_item", "news-1", "ev-shared"),
        ]
    ).paths[0]

    assert duplicate_path.duplicate_evidence_count > 0
    assert duplicate_path.path_score <= unique_path.path_score
    assert duplicate_path.guard_result is not None
    assert duplicate_path.guard_result.warnings


def _path_result(relations: list[Relation]):
    graph = CrossBoardGraphBuilder().build(relations=relations)
    return CrossBoardPathFinder().find_paths(graph)


def _relations() -> list[Relation]:
    return [
        _relation("proposes", "paper", "paper-1", "ev-paper"),
        _relation("implements", "project", "project-1", "ev-project"),
        _relation("discusses", "community_thread", "thread-1", "ev-community"),
        _relation("adopts", "news_item", "news-1", "ev-news"),
    ]


def _relation(relation_type: str, source_type: str, source_id: str, evidence_id: str) -> Relation:
    return Relation(
        relation_id=f"rel-{relation_type}-{source_id}",
        relation_type=RelationType(relation_type),
        source_ref=ObjectRef(object_type=source_type, object_id=source_id, label=source_id),
        target_ref=ObjectRef(object_type="technology", object_id="tech-agent-memory", label="Agent Memory"),
        evidence_signal_ids=[evidence_id],
        confidence=Confidence(value=0.84, evidence_count=1, reason="test evidence"),
    )
