from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from business.foundation.models import ObjectRef, Relation
from business.foundation.primitives import PrimitiveModel
from business.foundation.taxonomy import RelationType


class GraphNeighbor(PrimitiveModel):
    object_ref: ObjectRef
    relation: Relation
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class GraphRepository(Protocol):
    def upsert_relation(self, relation: Relation) -> None: ...

    def neighbors(self, object_ref: Any, relation_types: list[Any] | None) -> list[Any]: ...


@runtime_checkable
class IntelligenceGraphStore(Protocol):
    def upsert_object(self, object_ref: ObjectRef, properties: dict[str, Any]) -> None: ...

    def upsert_relation(self, relation: Relation) -> None: ...

    def neighbors(self, object_ref: ObjectRef, relation_types: list[RelationType] | None) -> list[GraphNeighbor]: ...


__all__ = ["GraphNeighbor", "GraphRepository", "IntelligenceGraphStore"]
