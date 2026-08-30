from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.memory.graph_memory import GraphMemoryService


@dataclass(frozen=True)
class GraphProjectionRequest:
    topic: str | None = None
    entity_id: str | None = None
    depth: int = 2
    limit: int = 100


@dataclass(frozen=True)
class GraphProjectionSummary:
    root_id: str | None
    node_count: int
    edge_count: int
    node_types: dict[str, int] = field(default_factory=dict)
    edge_types: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_id": self.root_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "node_types": dict(self.node_types),
            "edge_types": dict(self.edge_types),
            "metadata": dict(self.metadata),
        }


class GraphProjectionService:
    def __init__(self, graph_service: GraphMemoryService) -> None:
        self.graph_service = graph_service

    def summarize_entity_projection(self, request: GraphProjectionRequest) -> GraphProjectionSummary:
        if not request.entity_id:
            raise ValueError("entity_id is required")
        expansion = self.graph_service.expand_entity(
            request.entity_id,
            depth=request.depth,
            limit=request.limit,
        )
        return self._summarize(expansion)

    def _summarize(self, expansion: Any) -> GraphProjectionSummary:
        node_types: dict[str, int] = {}
        edge_types: dict[str, int] = {}
        for node in [expansion.root, *expansion.nodes]:
            node_type = str(node.node_type)
            node_types[node_type] = node_types.get(node_type, 0) + 1
        for edge in expansion.edges:
            edge_type = str(edge.edge_type)
            edge_types[edge_type] = edge_types.get(edge_type, 0) + 1
        return GraphProjectionSummary(
            root_id=expansion.root.node_id,
            node_count=1 + len(expansion.nodes),
            edge_count=len(expansion.edges),
            node_types=node_types,
            edge_types=edge_types,
            metadata=dict(expansion.metadata),
        )


__all__ = ["GraphProjectionRequest", "GraphProjectionService", "GraphProjectionSummary"]
