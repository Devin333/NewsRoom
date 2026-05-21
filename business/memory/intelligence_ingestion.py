from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from business.memory.claim_consolidation import ClaimConsolidator
from business.memory.entity_resolver import EntityResolver
from business.memory.event_builder import EventBuilder
from business.memory.intelligence_builder import IntelligenceMemoryBuilder
from business.memory.intelligence_models import IntelligenceMemoryBundle
from business.memory.intelligence_repository import (
    IntelligenceMemoryMutationRepository,
    IntelligenceMemoryQueryRepository,
    IntelligenceMemoryRepository,
    IntelligenceMemoryVectorIndex,
)


@dataclass(frozen=True, init=False)
class IntelligenceMemoryIngestionResult:
    run_id: str
    topic: str | None
    counts: dict[str, int]
    indexed_documents: int = 0
    collections: list[str] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    memories_written: int = 0
    memory_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        *,
        run_id: str = "",
        topic: str | None = None,
        counts: dict[str, int] | None = None,
        indexed_documents: int | None = None,
        documents_indexed: int | None = None,
        collections: list[str] | None = None,
        document_ids: list[str] | None = None,
        memories_written: int = 0,
        memory_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        resolved_indexed = indexed_documents if indexed_documents is not None else documents_indexed
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "topic", topic)
        object.__setattr__(self, "counts", dict(counts or _empty_counts()))
        object.__setattr__(self, "indexed_documents", int(resolved_indexed or 0))
        object.__setattr__(self, "collections", list(collections or []))
        object.__setattr__(self, "document_ids", list(document_ids or []))
        object.__setattr__(self, "memories_written", int(memories_written or 0))
        object.__setattr__(self, "memory_ids", list(memory_ids or []))
        object.__setattr__(self, "metadata", dict(metadata or {}))

    @property
    def documents_indexed(self) -> int:
        return self.indexed_documents

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "topic": self.topic,
            "counts": dict(self.counts),
            "indexed_documents": self.indexed_documents,
            "documents_indexed": self.indexed_documents,
            "collections": list(self.collections),
            "document_ids": list(self.document_ids),
            "memories_written": self.memories_written,
            "memory_ids": list(self.memory_ids),
            "metadata": dict(self.metadata),
        }


class IntelligenceMemoryIngestionService:
    def __init__(
        self,
        repository: IntelligenceMemoryRepository | None = None,
        *,
        query_repository: IntelligenceMemoryQueryRepository | None = None,
        builder: IntelligenceMemoryBuilder | None = None,
        entity_resolver: EntityResolver | None = None,
        claim_consolidator: ClaimConsolidator | None = None,
        event_builder: EventBuilder | None = None,
        vector_index: IntelligenceMemoryVectorIndex | None = None,
    ) -> None:
        self.repository = repository
        self.query_repository = query_repository or (
            repository if _has_structured_query_methods(repository) else None
        )
        self.builder = builder or IntelligenceMemoryBuilder()
        self.entity_resolver = entity_resolver or EntityResolver()
        self.claim_consolidator = claim_consolidator or ClaimConsolidator()
        self.event_builder = event_builder or EventBuilder()
        self.vector_index = vector_index

    def ingest_run_output(
        self,
        output: dict[str, Any],
        *,
        run_id: str,
        report_id: str | None = None,
        topic: str | None = None,
    ) -> IntelligenceMemoryIngestionResult:
        initial_bundle = self.builder.build_from_run_output(
            output,
            run_id=run_id,
            report_id=report_id,
            topic=topic,
        )
        return self.ingest_bundle(initial_bundle)

    def ingest_bundle(
        self,
        bundle: IntelligenceMemoryBundle,
    ) -> IntelligenceMemoryIngestionResult:
        final_bundle, metadata = self._prepare_bundle(bundle)
        self._save_bundle(final_bundle)
        indexed_documents, collections, document_ids = self._index_bundle(final_bundle)
        return IntelligenceMemoryIngestionResult(
            run_id=final_bundle.run_id,
            topic=final_bundle.topic,
            counts=final_bundle.counts(),
            indexed_documents=indexed_documents,
            collections=collections,
            document_ids=document_ids,
            metadata=metadata,
        )

    def _prepare_bundle(self, bundle: IntelligenceMemoryBundle) -> tuple[IntelligenceMemoryBundle, dict[str, Any]]:
        entity_result = self.entity_resolver.resolve_bundle(bundle)
        existing_claims = self._load_existing_claims(bundle)
        consolidation = self.claim_consolidator.consolidate(bundle.claims, existing_claims)
        final_claims = _dedupe_claims([*consolidation.inserted, *consolidation.merged, *consolidation.contradicted])
        existing_events = self._load_existing_events(bundle)
        event_result = self.event_builder.build_events(
            run_id=bundle.run_id,
            topic=bundle.topic,
            evidence=bundle.evidence,
            claims=final_claims,
            entities=entity_result.entities,
            existing_events=existing_events,
        )
        final_events = event_result.events if event_result.events else bundle.events
        final_bundle = replace(
            bundle,
            claims=final_claims or bundle.claims,
            entities=entity_result.entities,
            events=final_events,
        )
        metadata = {
            "claim_consolidation": consolidation.counts(),
            "entity_resolution": {
                "entities": len(entity_result.entities),
                "aliases_used": dict(entity_result.aliases_used),
                "unresolved": len(entity_result.unresolved_candidates),
            },
            "event_build": {
                "events": len(event_result.events),
                "duplicates": len(event_result.duplicate_event_ids),
                "skipped": len(event_result.skipped_candidates),
            },
        }
        return final_bundle, metadata

    def _load_existing_claims(self, bundle: IntelligenceMemoryBundle) -> list:
        if self.query_repository is None:
            return []
        claims = []
        if bundle.topic and hasattr(self.query_repository, "list_claims_by_topic"):
            claims.extend(self.query_repository.list_claims_by_topic(bundle.topic, limit=50))
        for claim in bundle.claims:
            if hasattr(self.query_repository, "find_similar_claims"):
                claims.extend(self.query_repository.find_similar_claims(claim, limit=10))
        return _dedupe_claims(claims)

    def _load_existing_events(self, bundle: IntelligenceMemoryBundle) -> list:
        if self.query_repository is None or not bundle.topic:
            return []
        if hasattr(self.query_repository, "list_events_by_topic"):
            return list(self.query_repository.list_events_by_topic(bundle.topic, limit=50))
        return []

    def _save_bundle(self, bundle: IntelligenceMemoryBundle) -> None:
        if self.repository is None:
            return
        self.repository.save_evidence(bundle.evidence)
        self.repository.save_claims(bundle.claims)
        self.repository.save_entities(bundle.entities)
        self.repository.save_events(bundle.events)
        self.repository.save_decisions(bundle.decisions)
        self.repository.save_preferences(bundle.preferences)

    def _index_bundle(self, bundle: IntelligenceMemoryBundle) -> tuple[int, list[str], list[str]]:
        if self.vector_index is None:
            return 0, [], []
        indexed_documents, collections, document_ids = self.vector_index.index_bundle(bundle)
        return int(indexed_documents), list(collections), list(document_ids)


def _empty_counts() -> dict[str, int]:
    return {
        "evidence": 0,
        "claims": 0,
        "entities": 0,
        "events": 0,
        "decisions": 0,
        "preferences": 0,
    }


def _dedupe_claims(claims: list) -> list:
    result = {}
    for claim in claims:
        result[claim.claim_id] = claim
    return list(result.values())


def _has_structured_query_methods(repository: object | None) -> bool:
    if repository is None:
        return False
    return all(
        callable(getattr(repository, name, None))
        for name in ("list_claims_by_topic", "find_similar_claims", "list_events_by_topic")
    )


__all__ = [
    "IntelligenceMemoryIngestionResult",
    "IntelligenceMemoryIngestionService",
]
