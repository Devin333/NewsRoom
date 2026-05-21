from __future__ import annotations

from typing import Any, Protocol

from business.foundation import BoardCard, BoardType
from business.memory.models import BusinessMemoryContext, BusinessMemoryHit


class BusinessMemorySearchPort(Protocol):
    def search(
        self,
        *,
        text: str,
        collection: str,
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> Any:
        ...


class BusinessMemoryRecallService:
    def __init__(self, search_port: BusinessMemorySearchPort | None = None) -> None:
        self.search_port = search_port

    def recall_for_card(
        self,
        card: BoardCard,
        *,
        board_type: BoardType,
        limit: int = 5,
    ) -> BusinessMemoryContext:
        query = f"{card.title} {card.summary}".strip()
        if self.search_port is None:
            return BusinessMemoryContext.empty(query, reason="memory_search_port_missing")
        collection = _collection_for_board(board_type)
        try:
            result_set = self.search_port.search(
                text=query,
                collection=collection,
                limit=limit,
                filters={"board_type": board_type.value},
            )
        except Exception as exc:
            return BusinessMemoryContext.empty(query, reason=f"memory_search_failed:{type(exc).__name__}")
        return BusinessMemoryContext(
            query=query,
            hits=self._hits_from_result_set(result_set),
            metadata={"memory_available": True, "collection": collection},
        )

    def recall_for_source(self, source_name: str, *, limit: int = 5) -> BusinessMemoryContext:
        if self.search_port is None:
            return BusinessMemoryContext.empty(source_name, reason="memory_search_port_missing")
        try:
            result_set = self.search_port.search(
                text=source_name,
                collection="evidence_items",
                limit=limit,
                filters={"source_name": source_name},
            )
        except Exception as exc:
            return BusinessMemoryContext.empty(source_name, reason=f"memory_search_failed:{type(exc).__name__}")
        return BusinessMemoryContext(query=source_name, hits=self._hits_from_result_set(result_set), metadata={"memory_available": True})

    def recall_for_topic(self, topic: str, *, limit: int = 8) -> BusinessMemoryContext:
        if self.search_port is None:
            return BusinessMemoryContext.empty(topic, reason="memory_search_port_missing")
        try:
            result_set = self.search_port.search(
                text=topic,
                collection="report_sections",
                limit=limit,
                filters={"topic": topic},
            )
        except Exception as exc:
            return BusinessMemoryContext.empty(topic, reason=f"memory_search_failed:{type(exc).__name__}")
        return BusinessMemoryContext(query=topic, hits=self._hits_from_result_set(result_set), metadata={"memory_available": True})

    def _hits_from_result_set(self, result_set: Any) -> list[BusinessMemoryHit]:
        if result_set is None:
            return []
        raw_results = getattr(result_set, "results", result_set)
        if callable(getattr(result_set, "to_dict", None)):
            payload = result_set.to_dict()
            raw_results = payload.get("results", raw_results) if isinstance(payload, dict) else raw_results
        return [BusinessMemoryHit.from_any(item) for item in list(raw_results or [])]


def _collection_for_board(board_type: BoardType) -> str:
    if board_type in {BoardType.AI_NEWS, BoardType.COMMUNITY_PULSE}:
        return "evidence_items"
    return "report_sections"
