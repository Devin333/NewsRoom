from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from business.foundation.primitives import PrimitiveModel
from business.foundation.taxonomy import ObjectType, RelationDirection, RelationType


class RelationDefinition(PrimitiveModel):
    relation_type: RelationType
    source_types: list[str] = Field(default_factory=list)
    target_types: list[str] = Field(default_factory=list)
    source_object_types: list[ObjectType] = Field(default_factory=list)
    target_object_types: list[ObjectType] = Field(default_factory=list)
    direction: RelationDirection = RelationDirection.DIRECTED
    directed: bool | None = None
    min_confidence: float = 0.5
    requires_evidence: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sync_direction_fields(self) -> "RelationDefinition":
        if self.directed is None:
            object.__setattr__(self, "directed", self.direction == RelationDirection.DIRECTED)
        else:
            object.__setattr__(
                self,
                "direction",
                RelationDirection.DIRECTED if self.directed else RelationDirection.UNDIRECTED,
            )
        return self


class RelationRegistry:
    def __init__(self, definitions: list[RelationDefinition] | None = None) -> None:
        self._definitions: dict[RelationType, RelationDefinition] = {}
        for definition in definitions or []:
            self.register(definition)

    def register(self, definition: RelationDefinition) -> None:
        self._definitions[definition.relation_type] = definition

    def get(self, relation_type: RelationType) -> RelationDefinition:
        return self._definitions[relation_type]

    def list(self) -> list[RelationDefinition]:
        return [self._definitions[key] for key in sorted(self._definitions, key=lambda item: item.value)]


def default_relation_registry() -> RelationRegistry:
    return RelationRegistry(
        [
            RelationDefinition(
                relation_type=RelationType.MENTIONS,
                source_types=["signal", "claim"],
                target_types=["entity", "topic", "technology"],
                min_confidence=0.5,
            ),
            RelationDefinition(
                relation_type=RelationType.PROPOSES,
                source_types=["paper", "claim"],
                target_types=["technology"],
                min_confidence=0.6,
            ),
            RelationDefinition(
                relation_type=RelationType.IMPLEMENTS,
                source_types=["project", "claim"],
                target_types=["technology", "paper"],
                min_confidence=0.65,
            ),
            RelationDefinition(
                relation_type=RelationType.DISCUSSES,
                source_types=["community_thread", "claim"],
                target_types=["project", "paper", "technology", "topic"],
                min_confidence=0.55,
            ),
            RelationDefinition(
                relation_type=RelationType.COMPARES,
                source_types=["claim", "community_thread", "paper"],
                target_types=["entity", "technology"],
                direction=RelationDirection.UNDIRECTED,
                min_confidence=0.6,
            ),
            RelationDefinition(
                relation_type=RelationType.ADOPTS,
                source_types=["signal", "claim"],
                target_types=["technology"],
                min_confidence=0.65,
            ),
            RelationDefinition(
                relation_type=RelationType.SUPPORTS,
                source_types=["signal", "claim"],
                target_types=["claim", "relation"],
                min_confidence=0.55,
            ),
            RelationDefinition(
                relation_type=RelationType.CRITICIZES,
                source_types=["community_thread", "claim"],
                target_types=["entity", "technology"],
                min_confidence=0.55,
            ),
            RelationDefinition(
                relation_type=RelationType.EXTENDS,
                source_types=["paper", "technology"],
                target_types=["technology"],
                min_confidence=0.6,
            ),
            RelationDefinition(
                relation_type=RelationType.SIMILAR_TO,
                source_types=["claim", "community_thread", "paper"],
                target_types=["technology"],
                direction=RelationDirection.UNDIRECTED,
                min_confidence=0.55,
            ),
            RelationDefinition(
                relation_type=RelationType.SAME_TOPIC,
                source_types=["signal"],
                target_types=["topic"],
                min_confidence=0.5,
            ),
        ]
    )


__all__ = ["RelationDefinition", "RelationRegistry", "default_relation_registry"]
