from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from evidence import EvidenceBundle
from domain.reports import FinalReport
from storage.vector import VectorDocument


REPORT_SECTIONS_COLLECTION = "report_sections"
EVIDENCE_ITEMS_COLLECTION = "evidence_items"


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
        final_report = output.get("final_report")
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
            section_sources = list(section.get("sources") or source_urls)
            doc_payload: dict[str, Any] = {
                "section_index": index,
                "section_title": title,
                "source_urls": section_sources,
                "report_title": payload.get("title"),
                "report_metadata": metadata,
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
            doc_payload: dict[str, Any] = {
                "bundle_id": bundle_id,
                "title": item.get("title"),
                "summary": item.get("summary"),
                "source_url": item.get("source_url"),
                "source_id": item.get("source_id"),
                "confidence": item.get("confidence"),
                "metadata": metadata,
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
                    source_item_id=item.get("source_id"),
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
