from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from business.memory.graph_memory import GraphMemoryService
from business.memory.graph_models import GraphQuery
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "paths": [path.to_dict() for path in self.paths],
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
        )

    def search_nodes(self, *, query: str, node_type: str | None = None, limit: int = 20) -> dict[str, Any]:
        graph_query = GraphQuery(
            node_type=node_type,  # type: ignore[arg-type]
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
    return GraphMemoryApplicationService(GraphMemoryService(PostgresGraphMemoryStore(repository)))


__all__ = [
    "GraphExpansionResult",
    "GraphMemoryApplicationService",
    "GraphPathResult",
    "graph_memory_service_from_env",
]
