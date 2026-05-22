from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, cast

from business.memory.graph_memory import GraphMemoryService
from business.memory.graph_models import GraphNodeType, GraphQuery
from interfaces.services.memory_service import _build_intelligence_repository_from_env
from infrastructure.storage.graph import PostgresGraphMemoryStore


@dataclass(frozen=True)
class GraphExpansionResult:
    target_id: str
    expansion: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "expansion": self.expansion.to_dict(),
        }


@dataclass(frozen=True)
class GraphPathResult:
    source_id: str
    target_id: str
    paths: list[Any]
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "paths": [path.to_dict() for path in self.paths],
            "metadata": dict(self.metadata or {}),
        }


class GraphMemoryApplicationService:
    def __init__(self, graph_service: GraphMemoryService) -> None:
        self.graph_service = graph_service

    def expand_entity(self, entity_id: str, *, depth: int = 2, limit: int = 50) -> GraphExpansionResult:
        return GraphExpansionResult(
            target_id=entity_id,
            expansion=self.graph_service.expand_entity(entity_id, depth=depth, limit=limit),
        )

    def expand_event(self, event_id: str, *, depth: int = 2, limit: int = 50) -> GraphExpansionResult:
        return GraphExpansionResult(
            target_id=event_id,
            expansion=self.graph_service.expand_event(event_id, depth=depth, limit=limit),
        )

    def paths_between(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 3,
        limit: int = 10,
    ) -> GraphPathResult:
        return GraphPathResult(
            source_id=source_id,
            target_id=target_id,
            paths=self.graph_service.paths_between(source_id, target_id, max_depth=max_depth, limit=limit),
            metadata=dict(getattr(self.graph_service.store, "last_path_metadata", {}) or {}),
        )

    def search_nodes(self, *, query: str, node_type: str | None = None, limit: int = 20) -> dict[str, Any]:
        resolved_node_type = _validate_node_type(node_type)
        graph_query = GraphQuery(
            node_type=resolved_node_type,
            limit=limit,
            metadata={"query": query},
        )
        nodes = self.graph_service.search_nodes(graph_query)
        return {
            "query": query,
            "node_type": node_type,
            "nodes": [node.to_dict() for node in nodes],
        }


def graph_memory_service_from_env(
    *,
    env: Mapping[str, str] | None = None,
) -> GraphMemoryApplicationService | None:
    repository = _build_intelligence_repository_from_env(env=env)
    if repository is None:
        return None
    return GraphMemoryApplicationService(GraphMemoryService(PostgresGraphMemoryStore(cast(Any, repository))))


__all__ = [
    "GraphExpansionResult",
    "GraphMemoryApplicationService",
    "GraphPathResult",
    "graph_memory_service_from_env",
]


def _validate_node_type(node_type: str | None) -> GraphNodeType | None:
    if node_type is None:
        return None
    allowed = {
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
    }
    if node_type not in allowed:
        valid = ", ".join(sorted(allowed))
        raise ValueError(f"invalid graph node_type: {node_type}; expected one of: {valid}")
    return cast(GraphNodeType, node_type)
