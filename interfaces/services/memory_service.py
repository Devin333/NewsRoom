from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from business.layers.memory.ingestion import (
    MemoryIngestionResult,
    MemoryIngestionService,
)
from business.memory.intelligence_repository import IntelligenceMemoryRepository, IntelligenceMemoryVectorIndex
from interfaces.services.artifact_service import ArtifactInspectionService
from infrastructure.storage.memory import IntelligenceVectorIndexAdapter
from infrastructure.storage.vector import VectorCollectionStatus, VectorSearchQuery, VectorSearchResult


DEFAULT_MEMORY_COLLECTION = "report_sections"
DEFAULT_BOOTSTRAP_COLLECTIONS = ("report_sections", "evidence_items")
TRUE_VALUES = {"1", "true", "yes", "on"}


class VectorSearchStore(Protocol):
    def search(self, query: VectorSearchQuery) -> list[VectorSearchResult]: ...

    def get_document(self, collection: str, document_id: str) -> VectorSearchResult | None: ...


class VectorMemoryStore(VectorSearchStore, Protocol):
    def upsert_documents(self, docs: list[Any]) -> None: ...

    def ensure_collections(self, collections: list[str]) -> list[VectorCollectionStatus]: ...


@dataclass(frozen=True)
class MemorySearchResultSet:
    collection: str
    query: str
    filters: dict[str, Any]
    limit: int
    results: list[VectorSearchResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "query": self.query,
            "filters": dict(self.filters),
            "limit": self.limit,
            "result_count": len(self.results),
            "results": [result.to_dict() for result in self.results],
        }


@dataclass(frozen=True)
class MemoryDocumentResult:
    collection: str
    document_id: str
    document: VectorSearchResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "document_id": self.document_id,
            "document": self.document.to_dict(),
        }


@dataclass(frozen=True)
class MemoryReindexResult:
    run_id: str
    topic: str | None
    ingestion: MemoryIngestionResult

    def to_dict(self) -> dict[str, Any]:
        ingestion_payload = _ingestion_to_dict(self.ingestion)
        return {
            "run_id": self.run_id,
            "topic": self.topic,
            "documents_indexed": self.ingestion.documents_indexed,
            "collections": list(self.ingestion.collections),
            "document_ids": list(self.ingestion.document_ids),
            "counts": dict(ingestion_payload.get("counts") or {}),
            "metadata": dict(ingestion_payload.get("metadata") or {}),
            "ingestion": ingestion_payload,
        }


@dataclass(frozen=True)
class MemoryBootstrapResult:
    collections: list[VectorCollectionStatus]

    def to_dict(self) -> dict[str, Any]:
        created = [status.collection for status in self.collections if status.created]
        existing = [status.collection for status in self.collections if status.existed_before]
        return {
            "collection_count": len(self.collections),
            "created_count": len(created),
            "existing_count": len(existing),
            "created_collections": created,
            "existing_collections": existing,
            "collections": [status.to_dict() for status in self.collections],
        }


class MemoryApplicationService:
    def __init__(
        self,
        vector_store: VectorMemoryStore | None = None,
        *,
        artifact_root: str | Path = ".newsroom/runs",
        artifact_service: ArtifactInspectionService | None = None,
        ingestion_service: MemoryIngestionService | None = None,
    ) -> None:
        if vector_store is None:
            from infrastructure.storage.vector import qdrant_store_from_env

            vector_store = qdrant_store_from_env()
        self.vector_store = vector_store
        self.artifact_service = artifact_service or ArtifactInspectionService(artifact_root)
        self.ingestion_service = ingestion_service or memory_ingestion_service_from_env(
            vector_store=self.vector_store,
        )
        if self.ingestion_service is None:
            if self.vector_store is None:
                raise ValueError("vector_store or memory ingestion sink is required")
            self.ingestion_service = MemoryIngestionService(self.vector_store)

    def search(
        self,
        *,
        text: str,
        collection: str = DEFAULT_MEMORY_COLLECTION,
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> MemorySearchResultSet:
        if self.vector_store is None:
            raise ValueError("vector_store is required for memory search")
        query = VectorSearchQuery(
            collection=collection,
            text=text,
            limit=limit,
            filters=filters or {},
        )
        return MemorySearchResultSet(
            collection=collection,
            query=text,
            filters=filters or {},
            limit=limit,
            results=self.vector_store.search(query),
        )

    def get_document(
        self,
        document_id: str,
        *,
        collection: str = DEFAULT_MEMORY_COLLECTION,
    ) -> MemoryDocumentResult:
        if self.vector_store is None:
            raise ValueError("vector_store is required for memory document lookup")
        if not document_id:
            raise ValueError("document_id is required")
        document = self.vector_store.get_document(collection, document_id)
        if document is None:
            raise FileNotFoundError(f"memory document not found: {document_id}")
        return MemoryDocumentResult(
            collection=collection,
            document_id=document_id,
            document=document,
        )

    def bootstrap_collections(
        self,
        collections: list[str] | None = None,
    ) -> MemoryBootstrapResult:
        if self.vector_store is None:
            raise ValueError("vector_store is required for memory bootstrap")
        requested = _normalize_collections(collections or list(DEFAULT_BOOTSTRAP_COLLECTIONS))
        return MemoryBootstrapResult(collections=self.vector_store.ensure_collections(requested))

    def reindex_run(self, run_id: str, *, topic: str | None = None) -> MemoryReindexResult:
        self.artifact_service.list_artifacts(run_id)
        output: dict[str, Any] = {}
        report = self._optional_artifact(run_id, "report_json")
        evidence_bundle = self._optional_artifact(run_id, "evidence_bundle")
        request = self._optional_artifact(run_id, "request")
        if report is not None:
            output["final_report"] = report
        if evidence_bundle is not None:
            output["evidence_bundle"] = evidence_bundle
        resolved_topic = topic or _request_topic(request)
        ingestion_service = self.ingestion_service
        if ingestion_service is None:
            raise ValueError("ingestion_service is required for memory reindex")
        ingestion = ingestion_service.ingest_run_output(
            output,
            run_id=run_id,
            report_id=f"{run_id}:final",
            topic=resolved_topic,
        )
        return MemoryReindexResult(run_id=run_id, topic=resolved_topic, ingestion=ingestion)

    def _optional_artifact(self, run_id: str, artifact_key: str) -> Any | None:
        try:
            return self.artifact_service.get_artifact(run_id, artifact_key).content
        except FileNotFoundError:
            return None


def _request_topic(request: Any) -> str | None:
    if not isinstance(request, dict):
        return None
    topic = request.get("topic")
    return str(topic) if topic else None


def _normalize_collections(collections: list[str]) -> list[str]:
    normalized = []
    seen = set()
    for collection in collections:
        value = str(collection).strip()
        if not value:
            raise ValueError("collection is required")
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def _ingestion_to_dict(ingestion: Any) -> dict[str, Any]:
    if hasattr(ingestion, "to_dict"):
        return dict(ingestion.to_dict())
    return {
        "run_id": getattr(ingestion, "run_id", ""),
        "topic": getattr(ingestion, "topic", None),
        "counts": dict(getattr(ingestion, "counts", {}) or {}),
        "indexed_documents": int(
            getattr(
                ingestion,
                "indexed_documents",
                getattr(ingestion, "documents_indexed", 0),
            )
            or 0
        ),
        "documents_indexed": int(getattr(ingestion, "documents_indexed", 0) or 0),
        "collections": list(getattr(ingestion, "collections", []) or []),
        "document_ids": list(getattr(ingestion, "document_ids", []) or []),
        "memories_written": int(getattr(ingestion, "memories_written", 0) or 0),
        "memory_ids": list(getattr(ingestion, "memory_ids", []) or []),
        "metadata": dict(getattr(ingestion, "metadata", {}) or {}),
    }


def memory_ingestion_service_from_env(
    *,
    env: Mapping[str, str] | None = None,
    vector_store: VectorMemoryStore | None = None,
    memory_runtime: Any | None = None,
) -> MemoryIngestionService | None:
    values = env if env is not None else os.environ
    if not _memory_enabled(values):
        return None
    vector_index: IntelligenceMemoryVectorIndex | None = None
    if vector_store is None:
        vector_store = _build_vector_index_from_env(env=values)
    if vector_store is not None:
        vector_index = IntelligenceVectorIndexAdapter(vector_store)
    repository = _build_intelligence_repository_from_env(env=values)
    if vector_store is None and repository is None and memory_runtime is None:
        return None
    return MemoryIngestionService(
        vector_store,
        memory_runtime=memory_runtime,
        repository=repository,
        vector_index=vector_index,
    )


def _memory_enabled(env: Mapping[str, str] | None = None) -> bool:
    values = env if env is not None else os.environ
    return (
        values.get("NEWS_MEMORY_ENABLED", "").lower() in TRUE_VALUES
        or values.get("NEWS_VECTOR_MEMORY_ENABLED", "").lower() in TRUE_VALUES
        or values.get("NEWS_MEMORY_POSTGRES_ENABLED", "").lower() in TRUE_VALUES
    )


def _build_intelligence_repository_from_env(
    *,
    env: Mapping[str, str] | None = None,
) -> IntelligenceMemoryRepository | None:
    values = env if env is not None else os.environ
    if values.get("NEWS_MEMORY_POSTGRES_ENABLED", "").lower() not in TRUE_VALUES:
        return None
    dsn = values.get("NEWS_DATABASE_DSN")
    if not dsn:
        return None
    from infrastructure.storage.postgres.memory_repository import PostgresIntelligenceMemoryRepository
    from infrastructure.storage.postgres.repository import PostgresRepository

    return PostgresIntelligenceMemoryRepository(PostgresRepository(dsn))


def _build_vector_index_from_env(
    *,
    env: Mapping[str, str] | None = None,
) -> VectorMemoryStore | None:
    values = env if env is not None else os.environ
    if values.get("NEWS_VECTOR_MEMORY_ENABLED", "").lower() not in TRUE_VALUES:
        return None
    from infrastructure.storage.vector import qdrant_store_from_env

    return qdrant_store_from_env(env=values)
