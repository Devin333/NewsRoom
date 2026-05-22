from __future__ import annotations

from typing import Any

from business.boards.cross_board.models import CrossBoardRelationView, RelationView
from business.foundation import BoardType, Relation


class RelationViewService:
    def build_views(self, relations: list[Relation]) -> list[CrossBoardRelationView]:
        return [self._view(relation) for relation in relations]

    def _view(self, relation: Relation) -> CrossBoardRelationView:
        explanation = _explain_relation(relation)
        return CrossBoardRelationView(
            source_board=_board_from_object(_object_type_value(relation.source_ref.object_type)),
            target_board=_board_from_object(_object_type_value(relation.target_ref.object_type)),
            relation=RelationView(
                relation_id=relation.relation_id,
                relation_type=relation.relation_type,
                source_label=relation.source_ref.label or relation.source_ref.object_id,
                target_label=relation.target_ref.label or relation.target_ref.object_id,
                explanation=explanation,
                confidence=relation.confidence,
            ),
            explanation=explanation,
        )


def _explain_relation(relation: Relation) -> str:
    source = relation.source_ref.label or relation.source_ref.object_id
    target = relation.target_ref.label or relation.target_ref.object_id
    templates = {
        "proposes": f"{source} proposes {target}.",
        "implements": f"{source} implements or applies {target}.",
        "discusses": f"Community discussion references {target}.",
        "adopts": f"{source} adopts or integrates {target}.",
        "compares": f"{source} compares with {target}.",
    }
    return templates.get(relation.relation_type.value, f"{source} {relation.relation_type.value} {target}.")


def _board_from_object(object_type: str) -> BoardType:
    if object_type == "paper":
        return BoardType.PAPER_RADAR
    if object_type == "project":
        return BoardType.PROJECT_RADAR
    if object_type == "community_thread":
        return BoardType.COMMUNITY_PULSE
    if object_type == "news_item":
        return BoardType.AI_NEWS
    return BoardType.CROSS_BOARD


def _object_type_value(value: Any) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)
