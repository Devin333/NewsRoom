from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from business.layers.output.memory_ingestion import (
    MemoryIngestionResult,
    MemoryIngestionService,
    MemoryIndexDocument,
)
from interfaces.services.artifact_service import ArtifactInspectionService
from storage.vector import VectorCollectionStatus, VectorSearchQuery, VectorSearchResult


DEFAULT_MEMORY_COLLECTION = "report_sections"
DEFAULT_BOOTSTRAP_COLLECTIONS = ("report_sections", "evidence_items")
TRUE_VALUES = {"1", "true", "yes", "on"}


class VectorSearchStore(Protocol):
    def search(self, query: VectorSearchQuery) -> list[VectorSearchResult]: ...

    def get_document(self, collection: str, document_id: str) -> VectorSearchResult | None: ...


class VectorMemoryStore(VectorSearchStore, Protocol):
    def upsert_documents(self, docs: list[MemoryIndexDocument]) -> None: ...

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
        return {
            "run_id": self.run_id,
            "topic": self.topic,
            "documents_indexed": self.ingestion.documents_indexed,
            "collections": list(self.ingestion.collections),
            "document_ids": list(self.ingestion.document_ids),
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
            from storage.vector import qdrant_store_from_env

            vector_store = qdrant_store_from_env()
        self.vector_store = vector_store
        self.artifact_service = artifact_service or ArtifactInspectionService(artifact_root)
        self.ingestion_service = ingestion_service or MemoryIngestionService(self.vector_store)

    def search(
        self,
        *,
        text: str,
        collection: str = DEFAULT_MEMORY_COLLECTION,
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> MemorySearchResultSet:
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
        ingestion = self.ingestion_service.ingest_run_output(
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


def memory_ingestion_service_from_env(
    *,
    env: dict[str, str] | None = None,
    vector_store: VectorMemoryStore | None = None,
    memory_runtime: Any | None = None,
) -> MemoryIngestionService | None:
    values = env if env is not None else os.environ
    enabled = values.get("NEWS_VECTOR_MEMORY_ENABLED", "").lower() in TRUE_VALUES
    if not enabled:
        return None
    if vector_store is None and memory_runtime is None:
        from storage.vector import qdrant_store_from_env

        vector_store = qdrant_store_from_env(env=values)
    return MemoryIngestionService(vector_store, memory_runtime=memory_runtime)
