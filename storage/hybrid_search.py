from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from storage.local_json import LocalJsonRepository
from storage.records import SearchResult
from storage.vector import VectorSearchQuery, VectorSearchResult


class VectorSearchStore(Protocol):
    def search(self, query: VectorSearchQuery) -> list[VectorSearchResult]: ...


@dataclass(frozen=True)
class HybridSearchQuery:
    query: str
    limit: int = 10
    collections: list[str] = field(default_factory=lambda: ["report_sections", "evidence_items"])
    filters: dict[str, Any] = field(default_factory=dict)


class HybridSearchService:
    def __init__(
        self,
        *,
        report_repository: LocalJsonRepository | None = None,
        vector_store: VectorSearchStore | None = None,
    ) -> None:
        self.report_repository = report_repository
        self.vector_store = vector_store

    def search(self, query: HybridSearchQuery | str) -> list[SearchResult]:
        actual_query = query if isinstance(query, HybridSearchQuery) else HybridSearchQuery(query=query)
        if actual_query.limit <= 0:
            raise ValueError("limit must be greater than zero")
        merged: dict[tuple[str, str], SearchResult] = {}
        if self.report_repository is not None:
            for record in self.report_repository.search_reports(actual_query.query, limit=actual_query.limit):
                result = SearchResult(
                    result_id=record.report_id,
                    result_type="report",
                    title=record.title,
                    snippet=record.title or record.report_id,
                    score=1.0,
                    keyword_score=1.0,
                    quality_score=record.quality_score,
                    refs={"run_id": record.run_id, "report_id": record.report_id},
                    metadata={
                        "manifest_path": str(record.manifest_path),
                        "workflow_id": record.workflow_id,
                        "profile": record.profile,
                    },
                )
                merged[(result.result_type, result.result_id)] = result

        if self.vector_store is not None:
            for collection in actual_query.collections:
                vector_query = VectorSearchQuery(
                    collection=collection,
                    text=actual_query.query,
                    filters=actual_query.filters,
                    limit=actual_query.limit,
                )
                for vector_result in self.vector_store.search(vector_query):
                    result = _search_result_from_vector(vector_result)
                    key = (result.result_type, result.result_id)
                    existing = merged.get(key)
                    if existing is None:
                        merged[key] = result
                    else:
                        merged[key] = _merge_scores(existing, result)

        results = list(merged.values())
        results.sort(key=lambda item: item.score, reverse=True)
        return results[: actual_query.limit]


def _search_result_from_vector(result: VectorSearchResult) -> SearchResult:
    result_type = {
        "report_section": "section",
        "evidence_item": "evidence",
        "source_chunk": "source_item",
    }.get(result.source_type, result.source_type or "memory")
    refs = {}
    if result.run_id:
        refs["run_id"] = result.run_id
    if result.report_id:
        refs["report_id"] = result.report_id
    if result.evidence_id:
        refs["evidence_id"] = result.evidence_id
    if result.source_item_id:
        refs["source_item_id"] = result.source_item_id
    payload = dict(result.payload)
    if result.section_id:
        refs["section_id"] = result.section_id
    elif payload.get("section_id"):
        refs["section_id"] = str(payload["section_id"])
    if payload.get("source_item_ids"):
        refs["source_item_ids"] = ",".join(str(value) for value in payload["source_item_ids"])
    return SearchResult(
        result_id=result.document_id,
        result_type=result_type,
        title=result.payload.get("section_title") or result.payload.get("title"),
        snippet=result.text,
        score=round(float(result.score), 6),
        semantic_score=round(float(result.score), 6),
        refs=refs,
        metadata=dict(result.payload),
    )


def _merge_scores(left: SearchResult, right: SearchResult) -> SearchResult:
    keyword_score = left.keyword_score if left.keyword_score is not None else right.keyword_score
    semantic_score = left.semantic_score if left.semantic_score is not None else right.semantic_score
    score = 0.0
    if keyword_score is not None:
        score += 0.4 * keyword_score
    if semantic_score is not None:
        score += 0.6 * semantic_score
    if score == 0.0:
        score = max(left.score, right.score)
    refs = dict(left.refs)
    refs.update(right.refs)
    metadata = dict(left.metadata)
    metadata.update(right.metadata)
    return SearchResult(
        result_id=left.result_id,
        result_type=left.result_type,
        title=left.title or right.title,
        snippet=left.snippet or right.snippet,
        score=round(score, 6),
        keyword_score=keyword_score,
        semantic_score=semantic_score,
        recency_score=left.recency_score or right.recency_score,
        quality_score=left.quality_score or right.quality_score,
        refs=refs,
        metadata=metadata,
    )
