from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from framework.harness.memory.ports import MemoryWriteCandidate, MemoryWriteStatus
from framework.memory import MemoryKind, MemoryQuery, MemoryScope, MemoryRuntime


DEFAULT_RAG_MEMORY_KINDS: tuple[MemoryKind, ...] = (MemoryKind.EPISODIC,)
DEFAULT_RAG_MEMORY_SCOPES: tuple[MemoryScope, ...] = (
    MemoryScope.SESSION,
    MemoryScope.WORKFLOW,
    MemoryScope.GLOBAL,
)


class ResearchRAGMemoryPort:
    """Map framework MemoryRuntime recall results into the harness RAG MemoryPort."""

    def __init__(
        self,
        memory_runtime: MemoryRuntime,
        *,
        kinds: Sequence[MemoryKind] = DEFAULT_RAG_MEMORY_KINDS,
        scopes: Sequence[MemoryScope] = DEFAULT_RAG_MEMORY_SCOPES,
        min_score: float | None = None,
    ) -> None:
        self._memory_runtime = memory_runtime
        self._kinds = tuple(kinds)
        self._scopes = tuple(scopes)
        self._min_score = min_score

    def recall(self, request: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        query = str(request.get("query") or "").strip()
        namespace = str(request.get("namespace") or "").strip() or None
        limit = max(1, int(request.get("limit") or 5))
        result = self._memory_runtime.recall(
            MemoryQuery(
                query=query,
                namespace=namespace,
                limit=limit,
                kinds=list(self._kinds),
                scopes=list(self._scopes),
                min_score=self._min_score,
            )
        )
        hits: list[dict[str, Any]] = []
        for item in result.results[:limit]:
            record = item.record
            hit_namespace = record.namespace or namespace
            if namespace is not None and hit_namespace != namespace:
                continue
            hits.append({
                "memory_id": record.memory_id,
                "memory_ref": _memory_ref(hit_namespace, record.memory_id),
                "namespace": hit_namespace,
                "kind": record.kind.value,
                "scope": record.scope.value,
                "summary": record.summary,
                "content": record.content,
                "text": record.content,
                "relevance": float(item.score),
                "score": float(item.score),
                "source": item.source,
                "refs": dict(record.refs) if isinstance(record.refs, dict) else {},
                "metadata": dict(record.metadata),
                "match_reasons": list(item.match_reasons),
            })
        return tuple(hits)

    def propose_write(self, candidate: MemoryWriteCandidate) -> MemoryWriteCandidate:
        return replace(candidate, status=MemoryWriteStatus.PROPOSED)


def _memory_ref(namespace: str | None, memory_id: str) -> str:
    if namespace:
        return f"memory://{namespace}/{memory_id}"
    return f"memory://{memory_id}"


__all__ = [
    "DEFAULT_RAG_MEMORY_KINDS",
    "DEFAULT_RAG_MEMORY_SCOPES",
    "ResearchRAGMemoryPort",
]
