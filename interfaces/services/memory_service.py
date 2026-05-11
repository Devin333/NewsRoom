from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from interfaces.services.artifact_service import ArtifactInspectionService
from storage.memory import MemoryIngestionResult, MemoryIngestionService
from storage.vector import VectorDocument, VectorSearchQuery, VectorSearchResult, qdrant_store_from_env


DEFAULT_MEMORY_COLLECTION = "report_sections"


class VectorSearchStore(Protocol):
    def search(self, query: VectorSearchQuery) -> list[VectorSearchResult]: ...


class VectorMemoryStore(VectorSearchStore, Protocol):
    def upsert_documents(self, docs: list[VectorDocument]) -> None: ...


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


class MemoryApplicationService:
    def __init__(
        self,
        vector_store: VectorMemoryStore | None = None,
        *,
        artifact_root: str | Path = ".newsroom/runs",
        artifact_service: ArtifactInspectionService | None = None,
        ingestion_service: MemoryIngestionService | None = None,
    ) -> None:
        self.vector_store = vector_store or qdrant_store_from_env()
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
