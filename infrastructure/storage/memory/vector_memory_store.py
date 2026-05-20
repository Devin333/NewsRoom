from __future__ import annotations

from typing import Any, Protocol

from framework.memory import (
    MemoryKind,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemorySearchResult,
    MemoryStore,
    MemoryWriteResult,
)
from framework.memory.exceptions import MemoryNotFound
from storage.vector import VectorDocument, VectorSearchQuery, VectorSearchResult


DEFAULT_MEMORY_COLLECTION = "memories"


class VectorDocumentStore(Protocol):
    def upsert_documents(self, docs: list[VectorDocument]) -> None:
        ...

    def search(self, query: VectorSearchQuery) -> list[VectorSearchResult]:
        ...

    def get_document(self, collection: str, document_id: str) -> VectorSearchResult | None:
        ...

    def delete_by_filter(self, collection: str, filters: dict[str, Any]) -> int:
        ...


class VectorMemoryStoreAdapter(MemoryStore):
    def __init__(
        self,
        vector_store: VectorDocumentStore,
        *,
        collection: str = DEFAULT_MEMORY_COLLECTION,
    ) -> None:
        self.vector_store = vector_store
        self.collection = collection

    def write(self, record: MemoryRecord) -> MemoryWriteResult:
        return self.write_many([record])

    def write_many(self, records: list[MemoryRecord]) -> MemoryWriteResult:
        docs = [_vector_document_from_record(record, collection=self.collection) for record in records]
        self.vector_store.upsert_documents(docs)
        return MemoryWriteResult(
            accepted_count=len(records),
            written_count=len(records),
            memory_ids=[record.memory_id for record in records],
        )

    def get(self, memory_id: str) -> MemoryRecord | None:
        result = self.vector_store.get_document(self.collection, memory_id)
        if result is None:
            return None
        return _record_from_vector_result(result)

    def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        filters = dict(query.filters)
        collection = str(filters.pop("collection", self.collection))
        vector_query = VectorSearchQuery(
            collection=collection,
            text=query.query,
            filters=filters,
            limit=max(query.limit, query.limit * 5),
            score_threshold=query.min_score,
        )
        results = [
            MemorySearchResult(
                record=_record_from_vector_result(result),
                score=result.score,
                source="vector",
                match_reasons=["vector_search"],
            )
            for result in self.vector_store.search(vector_query)
        ]
        filtered = [
            result
            for result in results
            if _matches_scope_and_kind(result.record, query)
        ]
        return filtered[: query.limit]

    def update(self, memory_id: str, patch: dict[str, Any]) -> MemoryRecord:
        existing = self.get(memory_id)
        if existing is None:
            raise MemoryNotFound(memory_id)
        updated = MemoryRecord.from_dict({**existing.to_dict(), **dict(patch), "memory_id": memory_id})
        self.write(updated)
        return updated

    def delete(self, memory_id: str) -> None:
        delete_by_filter = getattr(self.vector_store, "delete_by_filter", None)
        if not callable(delete_by_filter):
            raise NotImplementedError("vector memory delete is not implemented")
        delete_by_filter(self.collection, {"document_id": memory_id})


def _vector_document_from_record(record: MemoryRecord, *, collection: str) -> VectorDocument:
    payload = {
        **record.metadata,
        "memory_id": record.memory_id,
        "kind": record.kind.value,
        "scope": record.scope.value,
        "summary": record.summary,
        "metadata": dict(record.metadata),
        "refs": dict(record.refs),
        "tags": list(record.tags),
        "confidence": record.confidence,
        "importance": record.importance,
        "embedding": list(record.embedding) if record.embedding is not None else None,
        "actor": record.actor,
        "created_at": record.created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": record.updated_at.isoformat().replace("+00:00", "Z") if record.updated_at else None,
        "expires_at": record.expires_at.isoformat().replace("+00:00", "Z") if record.expires_at else None,
    }
    for key, value in record.refs.items():
        payload.setdefault(str(key), value)
    return VectorDocument(
        document_id=record.memory_id,
        collection=collection,
        text=record.content,
        payload=payload,
        source_type=record.kind.value,
        run_id=_optional_str(record.refs.get("run_id") or record.metadata.get("run_id")),
        report_id=_optional_str(record.refs.get("report_id") or record.metadata.get("report_id")),
        evidence_id=_optional_str(record.refs.get("evidence_id") or record.metadata.get("evidence_id")),
        source_item_id=_optional_str(record.refs.get("source_item_id") or record.metadata.get("source_item_id")),
        topic=_optional_str(record.metadata.get("topic")),
        section_id=_optional_str(record.refs.get("section_id") or record.metadata.get("section_id")),
        created_at=record.created_at,
        vector=list(record.embedding) if record.embedding is not None else None,
    )


def _record_from_vector_result(result: VectorSearchResult) -> MemoryRecord:
    payload = dict(result.payload)
    refs = dict(payload.get("refs") or {})
    for key, value in result.refs().items():
        refs.setdefault(key, value)
    metadata = dict(payload.get("metadata") or {})
    metadata.update(
        {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "memory_id",
                "document_id",
                "kind",
                "scope",
                "summary",
                "content",
                "text",
                "metadata",
                "refs",
                "tags",
                "confidence",
                "importance",
                "embedding",
                "actor",
                "created_at",
                "updated_at",
                "expires_at",
            }
        }
    )
    return MemoryRecord(
        memory_id=str(payload.get("memory_id") or result.document_id),
        kind=_memory_kind(payload.get("kind") or result.source_type),
        scope=_memory_scope(payload.get("scope")),
        summary=_optional_str(payload.get("summary") or payload.get("section_title") or payload.get("title")),
        content=str(payload.get("content") or payload.get("text") or result.text),
        metadata=metadata,
        refs=refs,
        tags=[str(item) for item in payload.get("tags") or []],
        confidence=_optional_float(payload.get("confidence")),
        importance=_optional_float(payload.get("importance")),
        embedding=_optional_float_list(payload.get("embedding")),
        actor=_optional_str(payload.get("actor")),
        created_at=payload.get("created_at") or None,
        updated_at=payload.get("updated_at") or None,
        expires_at=payload.get("expires_at") or None,
    )


def _matches_scope_and_kind(record: MemoryRecord, query: MemoryQuery) -> bool:
    if query.scopes and record.scope not in query.scopes:
        return False
    if query.kinds and record.kind not in query.kinds:
        return False
    if query.time_window is not None:
        if query.time_window.start is not None and record.created_at < query.time_window.start:
            return False
        if query.time_window.end is not None and record.created_at > query.time_window.end:
            return False
    return True


def _memory_kind(value: Any) -> MemoryKind:
    try:
        return MemoryKind(str(value))
    except ValueError:
        return MemoryKind.ARTIFACT


def _memory_scope(value: Any) -> MemoryScope:
    try:
        return MemoryScope(str(value))
    except ValueError:
        return MemoryScope.SESSION


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_float_list(value: Any) -> list[float] | None:
    if value is None:
        return None
    return [float(item) for item in value]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
