from __future__ import annotations

from datetime import datetime, timezone as _tz
from typing import Any

from framework import RunResult
from infrastructure.storage.records import (
    ClaimRecord,
    EvidenceItemRecord,
    QualityResultRecord,
    SourceItemRecord,
)
from infrastructure.storage.persistence.records import (
    ReportRecord,
    RunPersistenceBatch,
    WorkflowRunRecord,
)

UTC = _tz.utc


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
        "evidence_bundle_id": (
            report_payload.get("metadata", {}).get("evidence_bundle_id")
            if isinstance(report_payload.get("metadata"), dict)
            else None
        ),
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


__all__ = [
    "claim_records_from_result",
    "evidence_item_records_from_result",
    "quality_result_record_from_result",
    "report_record_from_result",
    "run_persistence_batch_from_result",
    "source_item_records_from_result",
    "workflow_run_record_from_result",
]
