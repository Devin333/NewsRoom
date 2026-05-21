from __future__ import annotations

from business.foundation import (
    BoardCard,
    BoardType,
    Confidence,
    ObjectRef,
    ObjectType,
    Score,
    SourceRef,
    SourceType,
)
from business.scoring import (
    community_pulse_feature_vector,
    paper_radar_feature_vector,
    project_radar_feature_vector,
)


def test_project_paper_and_community_feature_builders_return_vectors() -> None:
    project = project_radar_feature_vector(_card(BoardType.PROJECT_RADAR, "GitHub repo has releases and active commits"))
    paper = paper_radar_feature_vector(_card(BoardType.PAPER_RADAR, "Novel method with benchmark evaluation and ablation"))
    community = community_pulse_feature_vector(_card(BoardType.COMMUNITY_PULSE, "HN thread discusses bug concern and useful workaround"))

    assert "repo_health" in project.values
    assert "method_novelty" in paper.values
    assert "discussion_heat" in community.values


def _card(board_type: BoardType, summary: str) -> BoardCard:
    return BoardCard(
        card_id=f"{board_type.value}-card",
        board_type=board_type,
        title=summary,
        summary=summary,
        primary_object_ref=ObjectRef(object_type=ObjectType.NEWS_ITEM, object_id=f"{board_type.value}-1"),
        score=Score(value=0.5),
        confidence=Confidence(value=0.7),
        evidence_refs=[SourceRef(source_name="Source", source_type=SourceType.MANUAL)],
    )
