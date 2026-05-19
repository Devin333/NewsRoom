from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from core.framework import RunResult
from storage.local_json import LocalJsonRepository
from storage.records import (
    ClaimRecord,
    EvidenceItemRecord,
    QualityResultRecord,
    ReportDetailRecord,
    ReportSummaryRecord,
    SourceItemRecord,
)


@dataclass(frozen=True)
class WorkflowRunRecord:
    run_id: str
    workflow_id: str
    workflow_version: str
    status: str
    profile: str
    artifact_dir: str | None = None
    manifest_path: str | None = None
    events_path: str | None = None
    error: dict[str, Any] | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "status": self.status,
            "profile": self.profile,
            "artifact_dir": self.artifact_dir,
            "manifest_path": self.manifest_path,
            "events_path": self.events_path,
            "error": dict(self.error) if isinstance(self.error, dict) else self.error,
            "metrics": dict(self.metrics),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkflowRunRecord":
        return cls(
            run_id=str(payload["run_id"]),
            workflow_id=str(payload["workflow_id"]),
            workflow_version=str(payload["workflow_version"]),
            status=str(payload["status"]),
            profile=str(payload.get("profile") or ""),
            artifact_dir=payload.get("artifact_dir"),
            manifest_path=payload.get("manifest_path"),
            events_path=payload.get("events_path"),
            error=(
                dict(payload["error"])
                if isinstance(payload.get("error"), dict)
                else payload.get("error")
            ),
            metrics=dict(payload.get("metrics") or {}),
        )


@dataclass(frozen=True)
class ReportRecord:
    report_id: str
    run_id: str
    status: str
    title: str | None = None
    report_json: dict[str, Any] | None = None
    report_markdown: str | None = None
    quality_score: float | None = None
    citation_coverage_score: float | None = None
    manifest_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "status": self.status,
            "title": self.title,
            "report_json": dict(self.report_json) if isinstance(self.report_json, dict) else self.report_json,
            "report_markdown": self.report_markdown,
            "quality_score": self.quality_score,
            "citation_coverage_score": self.citation_coverage_score,
            "manifest_path": self.manifest_path,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReportRecord":
        return cls(
            report_id=str(payload["report_id"]),
            run_id=str(payload["run_id"]),
            status=str(payload["status"]),
            title=payload.get("title"),
            report_json=(
                dict(payload["report_json"])
                if isinstance(payload.get("report_json"), dict)
                else payload.get("report_json")
            ),
            report_markdown=payload.get("report_markdown"),
            quality_score=_optional_float(payload.get("quality_score")),
            citation_coverage_score=_optional_float(payload.get("citation_coverage_score")),
            manifest_path=payload.get("manifest_path"),
        )


@dataclass(frozen=True)
class RunPersistenceBatch:
    workflow_run: WorkflowRunRecord
    report: ReportRecord | None = None
    source_items: list[SourceItemRecord] = field(default_factory=list)
    evidence_items: list[EvidenceItemRecord] = field(default_factory=list)
    claims: list[ClaimRecord] = field(default_factory=list)
    quality_result: QualityResultRecord | None = None


class PersistenceRepository(Protocol):
    def migrate(self) -> None: ...

    def latest_report(self) -> ReportDetailRecord: ...

    def get_report(self, report_id: str) -> ReportDetailRecord: ...

    def list_reports(
        self,
        *,
        limit: int = 20,
        workflow_id: str | None = None,
        workflow_ids: tuple[str, ...] | None = None,
    ) -> list[ReportSummaryRecord]: ...

    def search_reports(self, query: str, *, limit: int = 20) -> list[ReportSummaryRecord]: ...

    def save_workflow_run(self, record: WorkflowRunRecord) -> None: ...

    def save_report(self, record: ReportRecord) -> None: ...

    def save_source_item(self, record: SourceItemRecord) -> None: ...

    def save_evidence_item(self, record: EvidenceItemRecord) -> None: ...

    def save_claim(self, record: ClaimRecord) -> None: ...

    def save_quality_result(self, record: QualityResultRecord) -> None: ...

    def save_run_records(self, batch: RunPersistenceBatch) -> None: ...

    def list_source_items(self, run_id: str) -> list[dict[str, Any]]: ...

    def list_evidence_items(self, run_id: str) -> list[dict[str, Any]]: ...

    def list_claims(self, run_id: str) -> list[dict[str, Any]]: ...

    def list_quality_results(self, run_id: str) -> list[dict[str, Any]]: ...


class LocalJsonPersistenceAdapter:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root)
        self.local_json = LocalJsonRepository(self.artifact_root)

    def latest_report(self) -> ReportDetailRecord:
        return _coerce_report_detail_record(self.local_json.latest_report())

    def get_report(self, report_id: str) -> ReportDetailRecord:
        return _coerce_report_detail_record(self.local_json.get_report(report_id))

    def list_reports(
        self,
        *,
        limit: int = 20,
        workflow_id: str | None = None,
        workflow_ids: tuple[str, ...] | None = None,
    ) -> list[ReportSummaryRecord]:
        return [
            _coerce_report_summary_record(record)
            for record in self.local_json.list_reports(
                limit=limit,
                workflow_id=workflow_id,
                workflow_ids=workflow_ids,
            )
        ]

    def search_reports(self, query: str, *, limit: int = 20) -> list[ReportSummaryRecord]:
        return [
            _coerce_report_summary_record(record)
            for record in self.local_json.search_reports(query, limit=limit)
        ]

    def migrate(self) -> None:
        (self.artifact_root / "_records" / "workflow_runs").mkdir(parents=True, exist_ok=True)
        (self.artifact_root / "_records" / "reports").mkdir(parents=True, exist_ok=True)
        (self.artifact_root / "_records" / "source_items").mkdir(parents=True, exist_ok=True)
        (self.artifact_root / "_records" / "evidence_items").mkdir(parents=True, exist_ok=True)
        (self.artifact_root / "_records" / "claims").mkdir(parents=True, exist_ok=True)
        (self.artifact_root / "_records" / "quality_results").mkdir(parents=True, exist_ok=True)

    def save_workflow_run(self, record: WorkflowRunRecord) -> None:
        self.migrate()
        _write_record_json(
            self.artifact_root / "_records" / "workflow_runs" / f"{_safe_record_name(record.run_id)}.json",
            record.to_dict(),
        )

    def save_report(self, record: ReportRecord) -> None:
        self.migrate()
        _write_record_json(
            self.artifact_root / "_records" / "reports" / f"{_safe_record_name(record.report_id)}.json",
            record.to_dict(),
        )

    def save_source_item(self, record: SourceItemRecord) -> None:
        self.migrate()
        _write_record_json(
            self.artifact_root
            / "_records"
            / "source_items"
            / _safe_record_name(record.run_id)
            / f"{_safe_record_name(record.source_item_id)}.json",
            record.to_dict(),
        )

    def save_evidence_item(self, record: EvidenceItemRecord) -> None:
        self.migrate()
        _write_record_json(
            self.artifact_root
            / "_records"
            / "evidence_items"
            / _safe_record_name(record.run_id)
            / f"{_safe_record_name(record.evidence_id)}.json",
            record.to_dict(),
        )

    def save_claim(self, record: ClaimRecord) -> None:
        self.migrate()
        _write_record_json(
            self.artifact_root
            / "_records"
            / "claims"
            / _safe_record_name(record.run_id)
            / f"{_safe_record_name(record.claim_id)}.json",
            record.to_dict(),
        )

    def save_quality_result(self, record: QualityResultRecord) -> None:
        self.migrate()
        _write_record_json(
            self.artifact_root
            / "_records"
            / "quality_results"
            / _safe_record_name(record.run_id)
            / f"{_safe_record_name(record.quality_result_id)}.json",
            record.to_dict(),
        )

    def save_run_records(self, batch: RunPersistenceBatch) -> None:
        self.save_workflow_run(batch.workflow_run)
        if batch.report is not None:
            self.save_report(batch.report)
        for source_item in batch.source_items:
            self.save_source_item(source_item)
        for evidence_item in batch.evidence_items:
            self.save_evidence_item(evidence_item)
        for claim in batch.claims:
            self.save_claim(claim)
        if batch.quality_result is not None:
            self.save_quality_result(batch.quality_result)

    def list_source_items(self, run_id: str) -> list[dict[str, Any]]:
        return _read_record_dir(self.artifact_root / "_records" / "source_items" / _safe_run_id(run_id))

    def list_evidence_items(self, run_id: str) -> list[dict[str, Any]]:
        return _read_record_dir(self.artifact_root / "_records" / "evidence_items" / _safe_run_id(run_id))

    def list_claims(self, run_id: str) -> list[dict[str, Any]]:
        return _read_record_dir(self.artifact_root / "_records" / "claims" / _safe_run_id(run_id))

    def list_quality_results(self, run_id: str) -> list[dict[str, Any]]:
        return _read_record_dir(
            self.artifact_root / "_records" / "quality_results" / _safe_run_id(run_id)
        )


def repository_from_env(
    *,
    artifact_root: str | Path = ".newsroom/runs",
    env: dict[str, str] | None = None,
) -> PersistenceRepository:
    values = env if env is not None else os.environ
    dsn = values.get("NEWS_DATABASE_DSN")
    if dsn:
        from storage.postgres.repository import PostgresRepository

        return PostgresRepository(dsn)
    return LocalJsonPersistenceAdapter(artifact_root)


def workflow_run_record_from_result(result: RunResult, *, profile: str) -> WorkflowRunRecord:
    return WorkflowRunRecord(
        run_id=result.run_id,
        workflow_id=result.workflow_id,
        workflow_version=result.workflow_version,
        status=result.status.value,
        profile=profile,
        artifact_dir=result.artifact_dir,
        manifest_path=result.manifest_path,
        events_path=result.events_path,
        error=result.error,
        metrics=_metrics_from_output(result.output),
    )


def report_record_from_result(result: RunResult) -> ReportRecord | None:
    final_report = result.output.get("final_report")
    blocked_report = result.output.get("blocked_report")
    quality_summary = result.output.get("report_quality_summary")
    if final_report is None and blocked_report is None:
        return None

    report_payload = _to_dict(final_report or blocked_report)
    quality_payload = _to_dict(quality_summary)
    quality_result = _to_dict(result.output.get("quality_result"))
    citation_check = _to_dict(result.output.get("citation_check_result"))
    support_matrix = _to_dict(result.output.get("support_matrix"))
    quality_trace = {
        "decision": quality_result.get("decision") or quality_payload.get("decision"),
        "route": quality_result.get("route") or result.output.get("quality_route"),
        "citation_failure_categories": quality_result.get("metadata", {}).get(
            "citation_failure_categories", []
        ),
        "unsupported_claims": citation_check.get("unsupported_claims", []),
        "rejected_claim_usage": citation_check.get("rejected_claim_usage", []),
        "unsupported_sections": support_matrix.get("unsupported_sections", []),
        "remediation": quality_result.get("metadata", {}).get("remediation", []),
        "reviewer_trace": quality_result.get("metadata", {}).get("reviewer_trace", {}),
        "accepted_claims_count": quality_result.get("metadata", {}).get("accepted_claims_count"),
        "rejected_claims_count": quality_result.get("metadata", {}).get("rejected_claims_count"),
        "uncertain_claims_count": quality_result.get("metadata", {}).get("uncertain_claims_count"),
        "unsupported_claims_count": quality_result.get("metadata", {}).get("unsupported_claims_count"),
        "evidence_bundle_id": report_payload.get("metadata", {}).get("evidence_bundle_id") if isinstance(report_payload.get("metadata"), dict) else None,
    }
    if report_payload:
        report_payload = {
            **report_payload,
            "quality_trace": quality_trace,
        }
    title = report_payload.get("title")
    status = "final" if final_report is not None else "blocked"
    quality_score = quality_payload.get("quality_score") if quality_payload else None
    citation_coverage_score = _citation_coverage_score(result.output)
    return ReportRecord(
        report_id=f"{result.run_id}:{status}",
        run_id=result.run_id,
        status=status,
        title=title,
        report_json=report_payload,
        report_markdown=result.output.get("report_markdown"),
        quality_score=quality_score,
        citation_coverage_score=citation_coverage_score,
        manifest_path=result.manifest_path,
    )


def persist_run_result(
    repository: PersistenceRepository,
    result: RunResult,
    *,
    profile: str,
    migrate: bool = True,
) -> None:
    if migrate:
        repository.migrate()
    batch = run_persistence_batch_from_result(result, profile=profile)
    save_batch = getattr(repository, "save_run_records", None)
    if save_batch is not None:
        save_batch(batch)
        return

    repository.save_workflow_run(batch.workflow_run)
    if batch.report:
        repository.save_report(batch.report)
    for source_item in batch.source_items:
        _optional_save(repository, "save_source_item", source_item)
    for evidence_item in batch.evidence_items:
        _optional_save(repository, "save_evidence_item", evidence_item)
    for claim in batch.claims:
        _optional_save(repository, "save_claim", claim)
    if batch.quality_result:
        _optional_save(repository, "save_quality_result", batch.quality_result)


def run_persistence_batch_from_result(result: RunResult, *, profile: str) -> RunPersistenceBatch:
    return RunPersistenceBatch(
        workflow_run=workflow_run_record_from_result(result, profile=profile),
        report=report_record_from_result(result),
        source_items=source_item_records_from_result(result),
        evidence_items=evidence_item_records_from_result(result),
        claims=claim_records_from_result(result),
        quality_result=quality_result_record_from_result(result),
    )


def source_item_records_from_result(result: RunResult) -> list[SourceItemRecord]:
    records = []
    for raw_item in result.output.get("raw_items", []) or []:
        payload = _object_payload(raw_item)
        source_item_id = str(payload.get("source_item_id") or "")
        if not source_item_id:
            continue
        metadata = dict(payload.get("metadata") or {})
        records.append(
            SourceItemRecord(
                source_item_id=source_item_id,
                run_id=result.run_id,
                source_id=str(payload.get("source_id") or ""),
                title=str(payload.get("title") or ""),
                url=str(payload.get("url") or ""),
                canonical_url=payload.get("canonical_url") or metadata.get("canonical_url"),
                published_at=_datetime_or_none(payload.get("published_at")),
                fetched_at=_datetime_or_none(payload.get("fetched_at")) or datetime.now(UTC),
                summary=payload.get("summary"),
                content_hash=payload.get("content_hash") or metadata.get("content_hash"),
                language=payload.get("language"),
                source_reliability=payload.get("source_reliability") or metadata.get("source_reliability"),
                raw_artifact_id=_artifact_id(payload.get("raw_artifact_ref")),
                metadata=metadata,
            )
        )
    return records


def evidence_item_records_from_result(result: RunResult) -> list[EvidenceItemRecord]:
    bundle = _object_payload(result.output.get("evidence_bundle"))
    records = []
    for item in bundle.get("items") or []:
        payload = _object_payload(item)
        evidence_id = str(payload.get("evidence_id") or "")
        if not evidence_id:
            continue
        lineage = _object_payload(payload.get("lineage"))
        metadata = dict(payload.get("metadata") or {})
        if not lineage:
            lineage = _object_payload(metadata.get("source_lineage"))
        source_item_id = lineage.get("source_item_id") or payload.get("source_id")
        records.append(
            EvidenceItemRecord(
                evidence_id=evidence_id,
                run_id=result.run_id,
                claim=str(payload.get("title") or ""),
                summary=str(payload.get("summary") or ""),
                source_urls=[str(payload.get("source_url") or "")],
                source_item_ids=[str(source_item_id)] if source_item_id else [],
                confidence=float(payload.get("confidence") or 0.0),
                category=str(metadata.get("category") or "news"),
                published_at=_datetime_or_none(lineage.get("published_at")),
                lineage_json=lineage,
                metadata=metadata,
            )
        )
    return records


def claim_records_from_result(result: RunResult) -> list[ClaimRecord]:
    findings = _object_payload(result.output.get("verified_findings"))
    records = []
    for status, key in [
        ("accepted", "accepted_claims"),
        ("rejected", "rejected_claims"),
        ("uncertain", "uncertain_claims"),
    ]:
        for claim in findings.get(key, []) or []:
            payload = _object_payload(claim)
            claim_id = str(payload.get("claim_id") or "")
            if not claim_id:
                continue
            records.append(
                ClaimRecord(
                    claim_id=claim_id,
                    run_id=result.run_id,
                    status=str(payload.get("status") or status),
                    text=str(payload.get("claim") or payload.get("text") or ""),
                    confidence=(
                        float(payload["confidence"]) if payload.get("confidence") is not None else None
                    ),
                    supporting_evidence_ids=[
                        str(value) for value in payload.get("supporting_evidence_ids", [])
                    ],
                    supporting_sources=[str(value) for value in payload.get("supporting_sources", [])],
                    rejecting_evidence_ids=[
                        str(value) for value in payload.get("rejecting_evidence_ids", [])
                    ],
                    rejecting_sources=[str(value) for value in payload.get("rejecting_sources", [])],
                    payload=payload,
                )
            )
    return records


def quality_result_record_from_result(result: RunResult) -> QualityResultRecord | None:
    quality_result = _to_dict(result.output.get("quality_result"))
    quality_summary = _to_dict(result.output.get("report_quality_summary"))
    editor_review = _to_dict(result.output.get("editor_review"))
    citation_check = _to_dict(result.output.get("citation_check_result"))
    if not quality_result and not quality_summary and not editor_review and not citation_check:
        return None
    decision = str(
        quality_result.get("decision")
        or editor_review.get("decision")
        or quality_summary.get("decision")
        or "unknown"
    )
    return QualityResultRecord(
        quality_result_id=f"{result.run_id}:quality",
        run_id=result.run_id,
        decision=decision,
        passed=bool(quality_result.get("passed")) if quality_result else decision == "pass",
        quality_score=_optional_float(
            _first_not_none(quality_result.get("quality_score"), quality_summary.get("quality_score"))
        ),
        citation_coverage_score=_optional_float(
            _first_not_none(
                quality_result.get("citation_coverage_score"),
                quality_summary.get("citation_coverage_score"),
                citation_check.get("citation_coverage_score"),
            )
        ),
        claim_support_score=_optional_float(
            _first_not_none(
                quality_result.get("claim_support_score"),
                quality_summary.get("claim_support_score"),
                citation_check.get("claim_support_score"),
            )
        ),
        evidence_alignment_score=_optional_float(
            _first_not_none(
                quality_result.get("evidence_alignment_score"),
                quality_summary.get("evidence_alignment_score"),
            )
        ),
        payload={
            "quality_result": quality_result,
            "quality_summary": quality_summary,
            "editor_review": editor_review,
            "citation_check": citation_check,
        },
    )


def _metrics_from_output(output: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key in [
        "source_pipeline_metrics",
        "agent_loop_metrics",
        "report_quality_summary",
        "quality_gate_metrics",
    ]:
        if key in output:
            metrics[key] = _to_dict(output[key])
    return metrics


def _citation_coverage_score(output: dict[str, Any]) -> float | None:
    quality_gate_metrics = _to_dict(output.get("quality_gate_metrics"))
    if "citation_coverage_score" in quality_gate_metrics:
        return quality_gate_metrics["citation_coverage_score"]
    citation_check = _to_dict(output.get("citation_check_result"))
    return citation_check.get("citation_coverage_score")


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return value
    return {}


def _object_payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        return payload if isinstance(payload, dict) else {}
    if isinstance(value, dict):
        return value
    return dict(value)


def _coerce_report_detail_record(record: Any) -> ReportDetailRecord:
    if isinstance(record, ReportDetailRecord):
        return record
    payload = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    return ReportDetailRecord(
        report_id=str(payload["report_id"]),
        run_id=str(payload["run_id"]),
        status=str(payload["status"]),
        finished_at=str(payload.get("finished_at") or ""),
        title=payload.get("title"),
        quality_score=_optional_float(payload.get("quality_score")),
        citation_coverage_score=_optional_float(payload.get("citation_coverage_score")),
        manifest_path=payload.get("manifest_path"),
        report_json_path=payload.get("report_json_path"),
        report_markdown_path=payload.get("report_markdown_path"),
        report_json=payload.get("report_json") if isinstance(payload.get("report_json"), dict) else None,
        report_markdown=payload.get("report_markdown"),
    )


def _coerce_report_summary_record(record: Any) -> ReportSummaryRecord:
    if isinstance(record, ReportSummaryRecord):
        return record
    payload = record.to_dict() if hasattr(record, "to_dict") else dict(record)
    return ReportSummaryRecord(
        report_id=str(payload["report_id"]),
        run_id=str(payload["run_id"]),
        status=str(payload["status"]),
        finished_at=str(payload.get("finished_at") or ""),
        title=payload.get("title"),
        quality_score=_optional_float(payload.get("quality_score")),
        citation_coverage_score=_optional_float(payload.get("citation_coverage_score")),
        workflow_id=payload.get("workflow_id"),
        profile=payload.get("profile"),
        manifest_path=payload.get("manifest_path"),
        report_json_path=payload.get("report_json_path"),
        report_markdown_path=payload.get("report_markdown_path"),
    )


def _write_record_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(temp_name).replace(path)
    except Exception:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
        raise


def _read_record_dir(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for record_path in sorted(path.glob("*.json")):
        try:
            payload = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _safe_record_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "record"


def _safe_run_id(value: str) -> str:
    if not value:
        raise ValueError("run_id is required")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise ValueError(f"invalid run_id: {value}")
    return _safe_record_name(value)


def _datetime_or_none(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _artifact_id(value: Any) -> str | None:
    payload = _object_payload(value)
    artifact_id = payload.get("artifact_id")
    return str(artifact_id) if artifact_id else None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _first_not_none(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _optional_save(repository: Any, method_name: str, record: Any) -> None:
    method = getattr(repository, method_name, None)
    if method is not None:
        method(record)
