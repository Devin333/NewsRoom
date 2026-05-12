from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


@dataclass(frozen=True)
class SourceItemRecord:
    source_item_id: str
    run_id: str
    source_id: str
    title: str
    url: str
    canonical_url: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime = field(default_factory=_utc_now)
    summary: str | None = None
    content_hash: str | None = None
    language: str | None = None
    source_reliability: str | None = None
    raw_artifact_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_item_id": self.source_item_id,
            "run_id": self.run_id,
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "canonical_url": self.canonical_url,
            "published_at": _dt(self.published_at),
            "fetched_at": _dt(self.fetched_at),
            "summary": self.summary,
            "content_hash": self.content_hash,
            "language": self.language,
            "source_reliability": self.source_reliability,
            "raw_artifact_id": self.raw_artifact_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvidenceItemRecord:
    evidence_id: str
    run_id: str
    claim: str
    summary: str
    source_urls: list[str]
    source_item_ids: list[str]
    confidence: float
    category: str = "news"
    published_at: datetime | None = None
    lineage_json: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "run_id": self.run_id,
            "claim": self.claim,
            "summary": self.summary,
            "source_urls": list(self.source_urls),
            "source_item_ids": list(self.source_item_ids),
            "confidence": self.confidence,
            "category": self.category,
            "published_at": _dt(self.published_at),
            "lineage_json": dict(self.lineage_json),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    run_id: str
    status: str
    text: str
    confidence: float | None = None
    supporting_evidence_ids: list[str] = field(default_factory=list)
    supporting_sources: list[str] = field(default_factory=list)
    rejecting_evidence_ids: list[str] = field(default_factory=list)
    rejecting_sources: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "run_id": self.run_id,
            "status": self.status,
            "text": self.text,
            "confidence": self.confidence,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "supporting_sources": list(self.supporting_sources),
            "rejecting_evidence_ids": list(self.rejecting_evidence_ids),
            "rejecting_sources": list(self.rejecting_sources),
            "payload": dict(self.payload),
            "created_at": _dt(self.created_at),
        }


@dataclass(frozen=True)
class QualityResultRecord:
    quality_result_id: str
    run_id: str
    decision: str
    passed: bool
    quality_score: float | None = None
    citation_coverage_score: float | None = None
    claim_support_score: float | None = None
    evidence_alignment_score: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality_result_id": self.quality_result_id,
            "run_id": self.run_id,
            "decision": self.decision,
            "passed": self.passed,
            "quality_score": self.quality_score,
            "citation_coverage_score": self.citation_coverage_score,
            "claim_support_score": self.claim_support_score,
            "evidence_alignment_score": self.evidence_alignment_score,
            "payload": dict(self.payload),
            "created_at": _dt(self.created_at),
        }


@dataclass(frozen=True)
class SearchResult:
    result_id: str
    result_type: str
    snippet: str
    score: float
    title: str | None = None
    keyword_score: float | None = None
    semantic_score: float | None = None
    recency_score: float | None = None
    quality_score: float | None = None
    refs: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "result_type": self.result_type,
            "title": self.title,
            "snippet": self.snippet,
            "score": self.score,
            "keyword_score": self.keyword_score,
            "semantic_score": self.semantic_score,
            "recency_score": self.recency_score,
            "quality_score": self.quality_score,
            "refs": dict(self.refs),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SchemaVersionedRecord:
    schema_version: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "data": dict(self.data),
        }


class StorageErrorType(str, Enum):
    ARTIFACT_WRITE_FAILED = "artifact_write_failed"
    ARTIFACT_READ_FAILED = "artifact_read_failed"
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_CHECKSUM_MISMATCH = "artifact_checksum_mismatch"
    RUN_STORE_WRITE_FAILED = "run_store_write_failed"
    RUN_STORE_READ_FAILED = "run_store_read_failed"
    REPORT_STORE_WRITE_FAILED = "report_store_write_failed"
    EVIDENCE_STORE_WRITE_FAILED = "evidence_store_write_failed"
    VECTOR_UPSERT_FAILED = "vector_upsert_failed"
    VECTOR_SEARCH_FAILED = "vector_search_failed"
    REDIS_QUEUE_FAILED = "redis_queue_failed"
    CHECKPOINT_SAVE_FAILED = "checkpoint_save_failed"
    CHECKPOINT_RESTORE_FAILED = "checkpoint_restore_failed"
    MIGRATION_FAILED = "migration_failed"
    SCHEMA_VERSION_MISMATCH = "schema_version_mismatch"
    REDACTION_FAILED = "redaction_failed"
    RETENTION_FAILED = "retention_failed"


@dataclass(frozen=True)
class StorageError:
    error_type: StorageErrorType | str
    message: str
    retryable: bool = False
    workflow_blocking: bool = False
    operator_action_required: bool = False
    data_integrity_risk: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "error_type", StorageErrorType(self.error_type))

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type.value,
            "message": self.message,
            "retryable": self.retryable,
            "workflow_blocking": self.workflow_blocking,
            "operator_action_required": self.operator_action_required,
            "data_integrity_risk": self.data_integrity_risk,
            "metadata": dict(self.metadata),
        }
