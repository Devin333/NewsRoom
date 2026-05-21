from __future__ import annotations

from business.boards.cross_board import CrossBoardGraphBuilder, CrossBoardPathFinder
from business.foundation import Confidence, ObjectRef, Relation, RelationType


def path_result(relations: list[Relation]):
    graph = CrossBoardGraphBuilder().build(relations=relations)
    return CrossBoardPathFinder().find_paths(graph)


def complete_relations(*, evidence_prefix: str = "ev") -> list[Relation]:
    return [
        relation("proposes", "paper", "paper-1", f"{evidence_prefix}-paper"),
        relation("implements", "project", "project-1", f"{evidence_prefix}-project"),
        relation("discusses", "community_thread", "thread-1", f"{evidence_prefix}-community"),
        relation("adopts", "news_item", "news-1", f"{evidence_prefix}-news"),
    ]


def relation(relation_type: str, source_type: str, source_id: str, evidence_id: str) -> Relation:
    return Relation(
        relation_id=f"rel-{relation_type}-{source_id}",
        relation_type=RelationType(relation_type),
        source_ref=ObjectRef(object_type=source_type, object_id=source_id, label=source_id),
        target_ref=ObjectRef(object_type="technology", object_id="tech-agent-memory", label="Agent Memory"),
        evidence_signal_ids=[evidence_id],
        confidence=Confidence(value=0.84, evidence_count=1, reason="test evidence"),
    )
