from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


GraphNodeType = Literal[
    "entity",
    "event",
    "claim",
    "evidence",
    "decision",
    "preference",
    "topic",
    "source",
    "report",
    "unknown",
]

GraphEdgeType = Literal[
    "involves",
    "has_claim",
    "supported_by",
    "contradicted_by",
    "affected",
    "applies_to",
    "published",
    "contains",
    "related_to",
]


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: GraphNodeType
    label: str
    summary: str | None = None
    score: float = 0.0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "label": self.label,
            "summary": self.summary,
            "score": self.score,
            "created_at": _dt(self.created_at),
            "updated_at": _dt(self.updated_at),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    source_id: str
    target_id: str
    edge_type: GraphEdgeType
    weight: float = 1.0
    confidence: float = 0.5
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_active(self) -> bool:
        return self.invalid_at is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type,
            "weight": self.weight,
            "confidence": self.confidence,
            "valid_at": _dt(self.valid_at),
            "invalid_at": _dt(self.invalid_at),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GraphPath:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    score: float = 0.0

    def length(self) -> int:
        return len(self.edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "score": self.score,
        }


@dataclass(frozen=True)
class GraphExpansion:
    root: GraphNode
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    depth: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root.to_dict(),
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "depth": self.depth,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GraphQuery:
    node_id: str | None = None
    node_type: GraphNodeType | None = None
    edge_types: list[GraphEdgeType] = field(default_factory=list)
    depth: int = 1
    limit: int = 50
    include_inactive: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


__all__ = [
    "GraphEdge",
    "GraphEdgeType",
    "GraphExpansion",
    "GraphNode",
    "GraphNodeType",
    "GraphPath",
    "GraphQuery",
]
