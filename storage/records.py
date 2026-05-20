from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _float_or_none(value: Any) -> float | None:
    return float(value) if value is not None else None


def _path_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


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

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SourceItemRecord":
        return cls(
            source_item_id=str(payload["source_item_id"]),
            run_id=str(payload["run_id"]),
            source_id=str(payload["source_id"]),
            title=str(payload.get("title") or ""),
            url=str(payload.get("url") or ""),
            canonical_url=payload.get("canonical_url"),
            published_at=_parse_dt(payload.get("published_at")),
            fetched_at=_parse_dt(payload.get("fetched_at")) or _utc_now(),
            summary=payload.get("summary"),
            content_hash=payload.get("content_hash"),
            language=payload.get("language"),
            source_reliability=payload.get("source_reliability"),
            raw_artifact_id=payload.get("raw_artifact_id"),
            metadata=_dict(payload.get("metadata")),
        )


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

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvidenceItemRecord":
        return cls(
            evidence_id=str(payload["evidence_id"]),
            run_id=str(payload["run_id"]),
            claim=str(payload.get("claim") or ""),
            summary=str(payload.get("summary") or ""),
            source_urls=_str_list(payload.get("source_urls")),
            source_item_ids=_str_list(payload.get("source_item_ids")),
            confidence=float(payload.get("confidence") or 0.0),
            category=str(payload.get("category") or "news"),
            published_at=_parse_dt(payload.get("published_at")),
            lineage_json=_dict(payload.get("lineage_json")),
            metadata=_dict(payload.get("metadata")),
        )


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

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ClaimRecord":
        return cls(
            claim_id=str(payload["claim_id"]),
            run_id=str(payload["run_id"]),
            status=str(payload.get("status") or "uncertain"),
            text=str(payload.get("text") or ""),
            confidence=_float_or_none(payload.get("confidence")),
            supporting_evidence_ids=_str_list(payload.get("supporting_evidence_ids")),
            supporting_sources=_str_list(payload.get("supporting_sources")),
            rejecting_evidence_ids=_str_list(payload.get("rejecting_evidence_ids")),
            rejecting_sources=_str_list(payload.get("rejecting_sources")),
            payload=_dict(payload.get("payload")),
            created_at=_parse_dt(payload.get("created_at")) or _utc_now(),
        )


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

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "QualityResultRecord":
        return cls(
            quality_result_id=str(payload["quality_result_id"]),
            run_id=str(payload["run_id"]),
            decision=str(payload.get("decision") or "unknown"),
            passed=bool(payload.get("passed")),
            quality_score=_float_or_none(payload.get("quality_score")),
            citation_coverage_score=_float_or_none(payload.get("citation_coverage_score")),
            claim_support_score=_float_or_none(payload.get("claim_support_score")),
            evidence_alignment_score=_float_or_none(payload.get("evidence_alignment_score")),
            payload=_dict(payload.get("payload")),
            created_at=_parse_dt(payload.get("created_at")) or _utc_now(),
        )


@dataclass(frozen=True)
class ReportDetailRecord:
    report_id: str
    run_id: str
    status: str
    finished_at: str
    title: str | None
    quality_score: float | None
    manifest_path: str | None
    report_json_path: str | None = None
    report_markdown_path: str | None = None
    report_json: dict[str, Any] | None = None
    report_markdown: str | None = None
    citation_coverage_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "status": self.status,
            "finished_at": self.finished_at,
            "title": self.title,
            "quality_score": self.quality_score,
            "citation_coverage_score": self.citation_coverage_score,
            "manifest_path": _path_or_none(self.manifest_path),
            "report_json_path": _path_or_none(self.report_json_path),
            "report_markdown_path": _path_or_none(self.report_markdown_path),
            "report_json": self.report_json,
            "report_markdown": self.report_markdown,
        }


@dataclass(frozen=True)
class ReportSummaryRecord:
    report_id: str
    run_id: str
    status: str
    finished_at: str
    title: str | None
    quality_score: float | None
    manifest_path: str | None
    report_json_path: str | None = None
    report_markdown_path: str | None = None
    citation_coverage_score: float | None = None
    workflow_id: str | None = None
    profile: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "status": self.status,
            "finished_at": self.finished_at,
            "title": self.title,
            "quality_score": self.quality_score,
            "citation_coverage_score": self.citation_coverage_score,
            "workflow_id": self.workflow_id,
            "profile": self.profile,
            "manifest_path": _path_or_none(self.manifest_path),
            "report_json_path": _path_or_none(self.report_json_path),
            "report_markdown_path": _path_or_none(self.report_markdown_path),
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

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SearchResult":
        return cls(
            result_id=str(payload["result_id"]),
            result_type=str(payload["result_type"]),
            snippet=str(payload.get("snippet") or ""),
            score=float(payload.get("score") or 0.0),
            title=payload.get("title"),
            keyword_score=_float_or_none(payload.get("keyword_score")),
            semantic_score=_float_or_none(payload.get("semantic_score")),
            recency_score=_float_or_none(payload.get("recency_score")),
            quality_score=_float_or_none(payload.get("quality_score")),
            refs={str(key): str(value) for key, value in _dict(payload.get("refs")).items()},
            metadata=_dict(payload.get("metadata")),
        )


@dataclass(frozen=True)
class SchemaVersionedRecord:
    schema_version: str
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SchemaVersionedRecord":
        return cls(
            schema_version=str(payload["schema_version"]),
            data=_dict(payload.get("data")),
        )


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

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StorageError":
        return cls(
            error_type=str(payload["error_type"]),
            message=str(payload.get("message") or ""),
            retryable=bool(payload.get("retryable")),
            workflow_blocking=bool(payload.get("workflow_blocking")),
            operator_action_required=bool(payload.get("operator_action_required")),
            data_integrity_risk=bool(payload.get("data_integrity_risk")),
            metadata=_dict(payload.get("metadata")),
        )
