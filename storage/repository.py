from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from core.framework import RunResult
from storage.local_json import LocalJsonRepository
from storage.records import ClaimRecord, EvidenceItemRecord, QualityResultRecord, SourceItemRecord


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


class PersistenceRepository(Protocol):
    def migrate(self) -> None: ...

    def save_workflow_run(self, record: WorkflowRunRecord) -> None: ...

    def save_report(self, record: ReportRecord) -> None: ...

    def save_source_item(self, record: SourceItemRecord) -> None: ...

    def save_evidence_item(self, record: EvidenceItemRecord) -> None: ...

    def save_claim(self, record: ClaimRecord) -> None: ...

    def save_quality_result(self, record: QualityResultRecord) -> None: ...


class LocalJsonPersistenceAdapter:
    def __init__(self, artifact_root: str | Path = ".newsroom/runs") -> None:
        self.artifact_root = Path(artifact_root)
        self.local_json = LocalJsonRepository(self.artifact_root)

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
            asdict(record),
        )

    def save_report(self, record: ReportRecord) -> None:
        self.migrate()
        _write_record_json(
            self.artifact_root / "_records" / "reports" / f"{_safe_record_name(record.report_id)}.json",
            asdict(record),
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

    def list_source_items(self, run_id: str) -> list[dict[str, Any]]:
        return _read_record_dir(self.artifact_root / "_records" / "source_items" / _safe_record_name(run_id))

    def list_evidence_items(self, run_id: str) -> list[dict[str, Any]]:
        return _read_record_dir(self.artifact_root / "_records" / "evidence_items" / _safe_record_name(run_id))

    def list_claims(self, run_id: str) -> list[dict[str, Any]]:
        return _read_record_dir(self.artifact_root / "_records" / "claims" / _safe_record_name(run_id))

    def list_quality_results(self, run_id: str) -> list[dict[str, Any]]:
        return _read_record_dir(
            self.artifact_root / "_records" / "quality_results" / _safe_record_name(run_id)
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
    title = report_payload.get("title")
    status = "final" if final_report is not None else "blocked"
    quality_score = None
    quality_payload = _to_dict(quality_summary)
    if quality_payload:
        quality_score = quality_payload.get("quality_score")
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
    repository.save_workflow_run(workflow_run_record_from_result(result, profile=profile))
    report = report_record_from_result(result)
    if report:
        repository.save_report(report)
    for source_item in source_item_records_from_result(result):
        _optional_save(repository, "save_source_item", source_item)
    for evidence_item in evidence_item_records_from_result(result):
        _optional_save(repository, "save_evidence_item", evidence_item)
    for claim in claim_records_from_result(result):
        _optional_save(repository, "save_claim", claim)
    quality_result = quality_result_record_from_result(result)
    if quality_result:
        _optional_save(repository, "save_quality_result", quality_result)


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
    quality_summary = _to_dict(result.output.get("report_quality_summary"))
    editor_review = _to_dict(result.output.get("editor_review"))
    citation_check = _to_dict(result.output.get("citation_check_result"))
    if not quality_summary and not editor_review and not citation_check:
        return None
    decision = str(editor_review.get("decision") or quality_summary.get("decision") or "unknown")
    return QualityResultRecord(
        quality_result_id=f"{result.run_id}:quality",
        run_id=result.run_id,
        decision=decision,
        passed=decision == "pass",
        quality_score=_optional_float(quality_summary.get("quality_score")),
        citation_coverage_score=_optional_float(
            quality_summary.get("citation_coverage_score")
            or citation_check.get("citation_coverage_score")
        ),
        claim_support_score=_optional_float(
            quality_summary.get("claim_support_score") or citation_check.get("claim_support_score")
        ),
        evidence_alignment_score=_optional_float(quality_summary.get("evidence_alignment_score")),
        payload={
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


def _write_record_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _read_record_dir(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(record_path.read_text(encoding="utf-8"))
        for record_path in sorted(path.glob("*.json"))
    ]


def _safe_record_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "record"


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


def _optional_save(repository: Any, method_name: str, record: Any) -> None:
    method = getattr(repository, method_name, None)
    if method is not None:
        method(record)
