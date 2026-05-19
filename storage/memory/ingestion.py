from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from evidence import EvidenceBundle
from domain.reports import FinalReport
from storage.vector import VectorDocument


REPORT_SECTIONS_COLLECTION = "report_sections"
EVIDENCE_ITEMS_COLLECTION = "evidence_items"
TRUE_VALUES = {"1", "true", "yes", "on"}


class VectorDocumentStore(Protocol):
    def upsert_documents(self, docs: list[VectorDocument]) -> None: ...


@dataclass(frozen=True)
class MemoryIngestionResult:
    documents_indexed: int
    collections: list[str]
    document_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "documents_indexed": self.documents_indexed,
            "collections": list(self.collections),
            "document_ids": list(self.document_ids),
        }


class MemoryIngestionService:
    def __init__(self, vector_store: VectorDocumentStore) -> None:
        self.vector_store = vector_store

    def ingest_report(
        self,
        report: FinalReport | dict[str, Any],
        *,
        run_id: str,
        report_id: str | None = None,
        topic: str | None = None,
    ) -> MemoryIngestionResult:
        docs = self.report_documents(report, run_id=run_id, report_id=report_id, topic=topic)
        self.vector_store.upsert_documents(docs)
        return _result_from_documents(docs)

    def ingest_evidence_bundle(
        self,
        bundle: EvidenceBundle | dict[str, Any],
        *,
        run_id: str,
        topic: str | None = None,
    ) -> MemoryIngestionResult:
        docs = self.evidence_documents(bundle, run_id=run_id, topic=topic)
        self.vector_store.upsert_documents(docs)
        return _result_from_documents(docs)

    def ingest_run_output(
        self,
        output: dict[str, Any],
        *,
        run_id: str,
        report_id: str | None = None,
        topic: str | None = None,
    ) -> MemoryIngestionResult:
        docs: list[VectorDocument] = []
        final_report = output.get("final_report") or output.get("blocked_report")
        evidence_bundle = output.get("evidence_bundle")
        if final_report is not None:
            docs.extend(self.report_documents(final_report, run_id=run_id, report_id=report_id, topic=topic))
        if evidence_bundle is not None:
            docs.extend(self.evidence_documents(evidence_bundle, run_id=run_id, topic=topic))
        if docs:
            self.vector_store.upsert_documents(docs)
        return _result_from_documents(docs)

    def report_documents(
        self,
        report: FinalReport | dict[str, Any],
        *,
        run_id: str,
        report_id: str | None = None,
        topic: str | None = None,
    ) -> list[VectorDocument]:
        payload = _to_dict(report)
        metadata = dict(payload.get("metadata") or {})
        resolved_report_id = report_id or f"{run_id}:final"
        resolved_topic = topic or metadata.get("topic")
        source_urls = list(payload.get("source_urls") or [])
        docs = []
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
                VectorDocument(
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

    def evidence_documents(
        self,
        bundle: EvidenceBundle | dict[str, Any],
        *,
        run_id: str,
        topic: str | None = None,
    ) -> list[VectorDocument]:
        payload = _to_dict(bundle)
        bundle_id = payload.get("bundle_id")
        docs = []
        for item in payload.get("items") or []:
            metadata = dict(item.get("metadata") or {})
            source_item_id = str(item.get("source_item_id") or "") or None
            source_item_ids = [str(value) for value in item.get("source_item_ids") or [] if value is not None]
            doc_payload: dict[str, Any] = {
                "bundle_id": bundle_id,
                "title": item.get("title"),
                "summary": item.get("summary"),
                "source_url": item.get("source_url"),
                "source_urls": [str(value) for value in item.get("source_urls") or [] if value is not None],
                "source_id": item.get("source_id"),
                "source_item_id": source_item_id,
                "source_item_ids": source_item_ids,
                "confidence": item.get("confidence"),
                "metadata": metadata,
                "refs": {
                    "run_id": run_id,
                    "evidence_id": str(item["evidence_id"]),
                    "source_item_id": source_item_id or str(item.get("source_id") or ""),
                },
            }
            if topic:
                doc_payload["topic"] = topic
            evidence_id = str(item["evidence_id"])
            docs.append(
                VectorDocument(
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


def _result_from_documents(docs: list[VectorDocument]) -> MemoryIngestionResult:
    collections = sorted({doc.collection for doc in docs})
    return MemoryIngestionResult(
        documents_indexed=len(docs),
        collections=collections,
        document_ids=[doc.document_id for doc in docs],
    )


def _to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value)


def memory_ingestion_service_from_env(
    *,
    env: dict[str, str] | None = None,
    vector_store: VectorDocumentStore | None = None,
) -> MemoryIngestionService | None:
    import os

    values = env if env is not None else os.environ
    enabled = values.get("NEWS_VECTOR_MEMORY_ENABLED", "").lower() in TRUE_VALUES
    if not enabled:
        return None
    if vector_store is None:
        from storage.vector import qdrant_store_from_env

        vector_store = qdrant_store_from_env(env=values)
    return MemoryIngestionService(vector_store)
