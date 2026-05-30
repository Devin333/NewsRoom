from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any, Protocol, cast

from business.memory.claim_consolidation import ClaimConsolidator
from business.memory.entity_resolver import EntityResolver
from business.memory.event_builder import EventBuilder
from business.memory.intelligence_builder import IntelligenceMemoryBuilder
from business.memory.intelligence_ingestion import IntelligenceMemoryIngestionService
from business.memory.intelligence_models import IntelligenceMemoryBundle
from business.memory.intelligence_repository import (
    IntelligenceMemoryQueryRepository,
    IntelligenceMemoryRepository,
    IntelligenceMemoryVectorIndex,
)
from framework.memory import MemoryKind, MemoryRecord, MemoryScope, MemoryWriteMode


REPORT_SECTIONS_COLLECTION = "report_sections"
EVIDENCE_ITEMS_COLLECTION = "evidence_items"


@dataclass(frozen=True)
class MemoryIndexDocument:
    document_id: str
    collection: str
    text: str
    payload: dict[str, Any] = field(default_factory=dict)
    source_type: str = "memory"
    vector: list[float] | None = None
    run_id: str | None = None
    report_id: str | None = None
    evidence_id: str | None = None
    source_item_id: str | None = None
    topic: str | None = None
    section_id: str | None = None
    published_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_id", _required_text(self.document_id, "document_id"))
        object.__setattr__(self, "collection", _required_text(self.collection, "collection"))
        object.__setattr__(self, "text", str(self.text))
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "source_type", _required_text(self.source_type, "source_type"))
        object.__setattr__(self, "vector", list(self.vector) if self.vector is not None else None)
        object.__setattr__(self, "published_at", _ensure_utc(self.published_at))
        object.__setattr__(self, "created_at", _ensure_utc(self.created_at) or self.created_at)

    def with_vector(self, vector: list[float]) -> "MemoryIndexDocument":
        return replace(self, vector=list(vector))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "collection": self.collection,
            "text": self.text,
            "source_type": self.source_type,
            "run_id": self.run_id,
            "report_id": self.report_id,
            "evidence_id": self.evidence_id,
            "source_item_id": self.source_item_id,
            "topic": self.topic,
            "section_id": self.section_id,
            "published_at": self.published_at.isoformat().replace("+00:00", "Z") if self.published_at else None,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
        }

    def to_payload(self) -> dict[str, Any]:
        payload = dict(self.payload)
        payload.update(
            {key: value for key, value in self.canonical_payload().items() if value is not None}
        )
        return payload


class MemoryIndexDocumentStore(Protocol):
    def upsert_documents(self, docs: list[MemoryIndexDocument]) -> None: ...


class MemoryRuntimeWriter(Protocol):
    def write(self, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, init=False)
class MemoryIngestionResult:
    run_id: str
    topic: str | None
    counts: dict[str, int]
    indexed_documents: int
    collections: list[str]
    document_ids: list[str]
    memories_written: int = 0
    memory_ids: list[str]
    metadata: dict[str, Any]

    def __init__(
        self,
        *,
        documents_indexed: int | None = None,
        indexed_documents: int | None = None,
        collections: list[str] | None = None,
        document_ids: list[str] | None = None,
        memories_written: int = 0,
        memory_ids: list[str] | None = None,
        run_id: str = "",
        topic: str | None = None,
        counts: dict[str, int] | None = None,
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


class MemoryIngestionService:
    def __init__(
        self,
        vector_store: MemoryIndexDocumentStore | None = None,
        *,
        memory_runtime: MemoryRuntimeWriter | None = None,
        repository: IntelligenceMemoryRepository | None = None,
        query_repository: IntelligenceMemoryQueryRepository | None = None,
        builder: IntelligenceMemoryBuilder | None = None,
        entity_resolver: EntityResolver | None = None,
        claim_consolidator: ClaimConsolidator | None = None,
        event_builder: EventBuilder | None = None,
        vector_index: IntelligenceMemoryVectorIndex | None = None,
    ) -> None:
        if vector_store is None and memory_runtime is None and repository is None and vector_index is None:
            raise ValueError("at least one memory sink is required")
        self.vector_store = vector_store
        self.memory_runtime = memory_runtime
        self.repository = repository
        self.vector_index = vector_index
        self.intelligence_ingestion = IntelligenceMemoryIngestionService(
            repository=repository,
            query_repository=query_repository,
            builder=builder,
            entity_resolver=entity_resolver,
            claim_consolidator=claim_consolidator,
            event_builder=event_builder,
            vector_index=vector_index,
        )
        self.builder = self.intelligence_ingestion.builder

    def ingest_report(
        self,
        report: Any,
        *,
        run_id: str,
        report_id: str | None = None,
        topic: str | None = None,
    ) -> MemoryIngestionResult:
        docs = self.report_documents(report, run_id=run_id, report_id=report_id, topic=topic)
        intelligence_bundle = self.builder.build_from_run_output(
            {"final_report": report},
            run_id=run_id,
            report_id=report_id,
            topic=topic,
        )
        return self._ingest_documents(
            docs,
            run_id=run_id,
            topic=topic,
            intelligence_bundle=intelligence_bundle,
        )

    def ingest_evidence_bundle(
        self,
        bundle: Any,
        *,
        run_id: str,
        topic: str | None = None,
    ) -> MemoryIngestionResult:
        docs = self.evidence_documents(bundle, run_id=run_id, topic=topic)
        output = {"evidence_bundle": bundle}
        intelligence_bundle = self.builder.build_from_run_output(output, run_id=run_id, topic=topic)
        return self._ingest_documents(
            docs,
            run_id=run_id,
            topic=topic,
            intelligence_bundle=intelligence_bundle,
        )

    def ingest_run_output(
        self,
        output: dict[str, Any],
        *,
        run_id: str,
        report_id: str | None = None,
        topic: str | None = None,
    ) -> MemoryIngestionResult:
        docs: list[MemoryIndexDocument] = []
        final_report = output.get("final_report") or output.get("blocked_report")
        evidence_bundle = output.get("evidence_bundle")
        if final_report is not None:
            docs.extend(self.report_documents(final_report, run_id=run_id, report_id=report_id, topic=topic))
        if evidence_bundle is not None:
            docs.extend(self.evidence_documents(evidence_bundle, run_id=run_id, topic=topic))
        intelligence_bundle = self.builder.build_from_run_output(
            output,
            run_id=run_id,
            report_id=report_id,
            topic=topic,
        )
        return self._ingest_documents(
            docs,
            run_id=run_id,
            topic=topic,
            intelligence_bundle=intelligence_bundle,
        )

    def report_documents(
        self,
        report: Any,
        *,
        run_id: str,
        report_id: str | None = None,
        topic: str | None = None,
    ) -> list[MemoryIndexDocument]:
        payload = _to_dict(report)
        metadata = dict(payload.get("metadata") or {})
        resolved_report_id = report_id or f"{run_id}:final"
        resolved_topic = topic or metadata.get("topic")
        source_urls = list(payload.get("source_urls") or [])
        docs: list[MemoryIndexDocument] = []
        for index, section in enumerate(payload.get("sections") or []):
            title = str(section.get("title") or f"Section {index + 1}")
            content = str(section.get("content") or "")
            section_id = str(section.get("section_id") or section.get("id") or f"section_{index + 1}")
            section_sources = list(section.get("sources") or source_urls)
            section_evidence_ids = [str(value) for value in (section.get("evidence_ids") or []) if value is not None]
            doc_payload: dict[str, Any] = {
                "section_index": index,
                "section_id": section_id,
                "section_title": title,
                "source_urls": section_sources,
                "evidence_ids": section_evidence_ids,
                "report_title": payload.get("title"),
                "report_metadata": metadata,
                "refs": {
                    "run_id": run_id,
                    "report_id": resolved_report_id,
                    "section_id": section_id,
                },
            }
            if resolved_topic:
                doc_payload["topic"] = resolved_topic
            docs.append(
                MemoryIndexDocument(
                    document_id=f"{run_id}:report_section:{index}",
                    collection=REPORT_SECTIONS_COLLECTION,
                    text=f"{title}\n{content}".strip(),
                    payload=doc_payload,
                    source_type="report_section",
                    run_id=run_id,
                    report_id=resolved_report_id,
                    section_id=section_id,
                    topic=resolved_topic,
                )
            )
        return docs

    def report_memory_records(
        self,
        report: Any,
        *,
        run_id: str,
        report_id: str | None = None,
        topic: str | None = None,
    ) -> list[MemoryRecord]:
        return [
            _memory_record_from_document(doc)
            for doc in self.report_documents(report, run_id=run_id, report_id=report_id, topic=topic)
        ]

    def evidence_documents(
        self,
        bundle: Any,
        *,
        run_id: str,
        topic: str | None = None,
    ) -> list[MemoryIndexDocument]:
        payload = _to_dict(bundle)
        bundle_id = payload.get("bundle_id")
        docs: list[MemoryIndexDocument] = []
        for item in payload.get("items") or []:
            metadata = dict(item.get("metadata") or {})
            source_item_id = str(item.get("source_item_id") or "") or None
            source_item_ids = [str(value) for value in item.get("source_item_ids") or [] if value is not None]
            evidence_id = str(item["evidence_id"])
            source_urls = [str(value) for value in item.get("source_urls") or [] if value is not None]
            if not source_urls and item.get("source_url"):
                source_urls = [str(item["source_url"])]
            doc_payload: dict[str, Any] = {
                "bundle_id": bundle_id,
                "title": item.get("title"),
                "summary": item.get("summary"),
                "source_url": item.get("source_url"),
                "source_urls": source_urls,
                "source_id": item.get("source_id"),
                "source_item_id": source_item_id,
                "source_item_ids": source_item_ids,
                "confidence": item.get("confidence"),
                "metadata": metadata,
                "refs": {
                    "run_id": run_id,
                    "evidence_id": evidence_id,
                    "source_item_id": source_item_id or str(item.get("source_id") or ""),
                },
            }
            if topic:
                doc_payload["topic"] = topic
            docs.append(
                MemoryIndexDocument(
                    document_id=f"{run_id}:evidence:{evidence_id}",
                    collection=EVIDENCE_ITEMS_COLLECTION,
                    text=f"{item.get('title') or ''}\n{item.get('summary') or ''}".strip(),
                    payload=doc_payload,
                    source_type="evidence_item",
                    run_id=run_id,
                    evidence_id=evidence_id,
                    source_item_id=source_item_id or item.get("source_id"),
                    topic=topic,
                )
            )
        return docs

    def evidence_memory_records(
        self,
        bundle: Any,
        *,
        run_id: str,
        topic: str | None = None,
    ) -> list[MemoryRecord]:
        return [
            _memory_record_from_document(doc)
            for doc in self.evidence_documents(bundle, run_id=run_id, topic=topic)
        ]

    def _ingest_documents(
        self,
        docs: list[MemoryIndexDocument],
        *,
        run_id: str,
        topic: str | None = None,
        intelligence_bundle: IntelligenceMemoryBundle | None = None,
    ) -> MemoryIngestionResult:
        vector_result = _result_from_documents(docs)
        if docs and self.vector_store is not None:
            self.vector_store.upsert_documents(docs)
        intelligence_indexed = 0
        intelligence_collections: list[str] = []
        intelligence_document_ids: list[str] = []
        if intelligence_bundle is not None:
            intelligence_result = self.intelligence_ingestion.ingest_bundle(intelligence_bundle)
            intelligence_indexed = intelligence_result.indexed_documents
            intelligence_collections = list(intelligence_result.collections)
            intelligence_document_ids = list(intelligence_result.document_ids)
            intelligence_counts = dict(intelligence_result.counts)
            intelligence_metadata = dict(intelligence_result.metadata)
        else:
            intelligence_counts = _empty_counts()
            intelligence_metadata = {}
        memory_ids: list[str] = []
        memories_written = 0
        if docs and self.memory_runtime is not None:
            records = [_memory_record_from_document(doc) for doc in docs]
            write_result = self.memory_runtime.write(
                records=records,
                mode=MemoryWriteMode.UPSERT,
                actor="business.layers.memory.ingestion",
                run_id=run_id,
            )
            memories_written = int(getattr(write_result, "written_count", 0) or 0)
            memory_ids = [str(memory_id) for memory_id in getattr(write_result, "memory_ids", [])]
        return MemoryIngestionResult(
            run_id=run_id,
            topic=topic or (intelligence_bundle.topic if intelligence_bundle else None),
            counts=intelligence_counts,
            indexed_documents=vector_result.documents_indexed + int(intelligence_indexed),
            collections=sorted({*vector_result.collections, *intelligence_collections}),
            document_ids=[*vector_result.document_ids, *intelligence_document_ids],
            memories_written=memories_written,
            memory_ids=memory_ids,
            metadata=intelligence_metadata,
        )


def _result_from_documents(docs: list[MemoryIndexDocument]) -> MemoryIngestionResult:
    collections = sorted({doc.collection for doc in docs})
    return MemoryIngestionResult(
        documents_indexed=len(docs),
        collections=collections,
        document_ids=[doc.document_id for doc in docs],
    )


def _empty_counts() -> dict[str, int]:
    return {
        "evidence": 0,
        "claims": 0,
        "entities": 0,
        "events": 0,
        "decisions": 0,
        "preferences": 0,
    }


def _memory_record_from_document(doc: MemoryIndexDocument) -> MemoryRecord:
    payload = doc.to_payload()
    refs = dict(payload.get("refs") or {})
    for key in ("run_id", "report_id", "evidence_id", "source_item_id", "section_id"):
        value = payload.get(key)
        if value is not None:
            refs.setdefault(key, value)
    metadata = dict(payload)
    metadata.pop("refs", None)
    return MemoryRecord(
        memory_id=doc.document_id,
        scope=MemoryScope.SESSION,
        kind=MemoryKind.ARTIFACT,
        content=doc.text,
        summary=_memory_summary(doc, payload),
        metadata=metadata,
        refs=refs,
        tags=[doc.collection, doc.source_type],
        confidence=_optional_float(payload.get("confidence")) or 1.0,
        importance=0.5,
        actor="business.layers.memory.ingestion",
        created_at=doc.created_at,
    )


def _memory_summary(doc: MemoryIndexDocument, payload: dict[str, Any]) -> str | None:
    summary = payload.get("summary") or payload.get("section_title") or payload.get("title")
    if summary:
        return str(summary)
    text = doc.text.strip()
    return text[:160] if text else None


def _to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(cast(Any, value))
    return dict(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _required_text(value: Any, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "EVIDENCE_ITEMS_COLLECTION",
    "MemoryIndexDocument",
    "MemoryIndexDocumentStore",
    "MemoryIngestionResult",
    "MemoryIngestionService",
    "MemoryRuntimeWriter",
    "REPORT_SECTIONS_COLLECTION",
]
