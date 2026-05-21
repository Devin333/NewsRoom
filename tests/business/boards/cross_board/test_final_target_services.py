from __future__ import annotations

from business.boards.cross_board.regression_guard import guard_cross_board_insight
from business.boards.cross_board.relation_view_service import RelationViewService
from business.boards.cross_board.technology_journey_service import TechnologyJourneyService
from business.foundation import Confidence, ObjectRef, Relation, RelationDirection, RelationType


def test_cross_board_relation_views_and_journey_use_processed_relations() -> None:
    tech = ObjectRef(object_type="technology", object_id="tech-agent-memory", label="Agent Memory")
    relation = Relation(
        relation_id="rel-1",
        relation_type=RelationType.IMPLEMENTS,
        source_ref=ObjectRef(object_type="project", object_id="proj-1", label="example/agent-memory"),
        target_ref=tech,
        direction=RelationDirection.DIRECTED,
        evidence_signal_ids=["sig-1"],
        confidence=Confidence(value=0.8),
    )

    views = RelationViewService().build_views([relation])
    journey = TechnologyJourneyService().build_journey(tech, [relation])

    assert views[0].relation.relation_type == RelationType.IMPLEMENTS
    assert journey.stages[0].stage_type == "project_implementation"
    assert journey.stages[0].evidence_relation_ids == ["rel-1"]


def test_cross_board_guard_blocks_unsupported_insight() -> None:
    result = guard_cross_board_insight(evidence_count=0, board_support_count=1, confidence=0.4)

    assert result.status == "block"
    assert not result.passed
    assert result.blocking_reasons
