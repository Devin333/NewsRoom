from __future__ import annotations

from typing import Any, Protocol


class GraphMemoryPort(Protocol):
    def upsert_node(self, node: Any) -> None: ...

    def upsert_edge(self, edge: Any) -> None: ...

    def get_node(self, node_id: str) -> Any | None: ...

    def neighbors(
        self,
        node_id: str,
        *,
        depth: int = 1,
        edge_types: list[str] | None = None,
        limit: int = 50,
    ) -> Any: ...

    def paths_between(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 3,
        limit: int = 10,
    ) -> list[Any]: ...

    def search_nodes(self, query: Any) -> list[Any]: ...


__all__ = ["GraphMemoryPort"]
