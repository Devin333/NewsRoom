from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from business.memory.graph_models import GraphEdge, GraphExpansion, GraphNode, GraphPath, GraphQuery


class GraphMemoryPort(Protocol):
    def upsert_node(self, node: GraphNode) -> None: ...

    def upsert_edge(self, edge: GraphEdge) -> None: ...

    def get_node(self, node_id: str) -> GraphNode | None: ...

    def neighbors(
        self,
        node_id: str,
        *,
        depth: int = 1,
        edge_types: list[str] | None = None,
        limit: int = 50,
    ) -> GraphExpansion: ...

    def paths_between(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 3,
        limit: int = 10,
    ) -> list[GraphPath]: ...

    def search_nodes(self, query: GraphQuery) -> list[GraphNode]: ...


@dataclass(frozen=True)
class GraphMemoryProjectionResult:
    nodes_written: int
    edges_written: int
    metadata: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "nodes_written": self.nodes_written,
            "edges_written": self.edges_written,
            "metadata": dict(self.metadata),
        }


class GraphMemoryService:
    def __init__(self, store: GraphMemoryPort) -> None:
        self.store = store

    def get_node(self, node_id: str) -> GraphNode | None:
        return self.store.get_node(node_id)

    def expand_entity(self, entity_id: str, *, depth: int = 2, limit: int = 50) -> GraphExpansion:
        return self.store.neighbors(entity_id, depth=depth, limit=limit)

    def expand_event(self, event_id: str, *, depth: int = 2, limit: int = 50) -> GraphExpansion:
        return self.store.neighbors(event_id, depth=depth, limit=limit)

    def paths_between(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 3,
        limit: int = 10,
    ) -> list[GraphPath]:
        return self.store.paths_between(source_id, target_id, max_depth=max_depth, limit=limit)

    def search_nodes(self, query: GraphQuery) -> list[GraphNode]:
        return self.store.search_nodes(query)


__all__ = ["GraphMemoryPort", "GraphMemoryProjectionResult", "GraphMemoryService"]
