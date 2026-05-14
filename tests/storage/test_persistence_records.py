import json

import pytest

from core.framework.run_result import RunResult
from core.framework.specs import WorkflowStatus
from domain.reports import BlockedReport, FinalReport
from evidence import EvidenceBundle, EvidenceItem, VerifiedClaim, VerifiedFindings
from quality import QualityGateMetrics, ReportQualitySummary
from storage.records import ClaimRecord, EvidenceItemRecord, QualityResultRecord, SourceItemRecord
from storage.repository import (
    LocalJsonPersistenceAdapter,
    ReportRecord,
    RunPersistenceBatch,
    WorkflowRunRecord,
    claim_records_from_result,
    evidence_item_records_from_result,
    persist_run_result,
    quality_result_record_from_result,
    report_record_from_result,
    run_persistence_batch_from_result,
    source_item_records_from_result,
    workflow_run_record_from_result,
)


def test_workflow_run_record_from_result_extracts_metrics() -> None:
    result = RunResult(
        run_id="run-1",
        workflow_id="daily",
        workflow_version="1",
        status=WorkflowStatus.SUCCEEDED,
        output={
            "report_quality_summary": ReportQualitySummary(
                quality_score=0.9,
                support_coverage=1.0,
                citation_passed=True,
            ),
            "quality_gate_metrics": QualityGateMetrics(
                evidence_items_count=2,
                unsupported_urls_count=0,
                missing_section_sources_count=0,
                unsupported_sections_count=0,
                blocked=False,
                decision="pass",
                citation_coverage_score=0.75,
                support_coverage=1.0,
                quality_score=0.9,
            ),
        },
        artifact_dir="runs/run-1",
        manifest_path="runs/run-1/manifest.json",
        events_path="runs/run-1/events.jsonl",
    )

    record = workflow_run_record_from_result(result, profile="live-offline")

    assert record.run_id == "run-1"
    assert record.status == "succeeded"
    assert record.profile == "live-offline"
    assert record.metrics["report_quality_summary"]["quality_score"] == 0.9
    assert record.metrics["quality_gate_metrics"]["citation_coverage_score"] == 0.75


def test_report_record_from_result_extracts_final_report() -> None:
    result = RunResult(
        run_id="run-1",
        workflow_id="daily",
        workflow_version="1",
        status=WorkflowStatus.SUCCEEDED,
        output={
            "final_report": FinalReport(
                title="Daily",
                sections=[],
                source_urls=[],
            ),
            "report_markdown": "# Daily\n",
            "report_quality_summary": ReportQualitySummary(
                quality_score=1.0,
                support_coverage=1.0,
                citation_passed=True,
            ),
            "quality_gate_metrics": QualityGateMetrics(
                evidence_items_count=1,
                unsupported_urls_count=0,
                missing_section_sources_count=0,
                unsupported_sections_count=0,
                blocked=False,
                decision="pass",
                citation_coverage_score=1.0,
                support_coverage=1.0,
                quality_score=1.0,
            ),
        },
        manifest_path="runs/run-1/manifest.json",
    )

    record = report_record_from_result(result)

    assert record is not None
    assert record.report_id == "run-1:final"
    assert record.title == "Daily"
    assert record.status == "final"
    assert record.quality_score == 1.0
    assert record.citation_coverage_score == 1.0


def test_report_record_from_result_preserves_blocked_report_status() -> None:
    result = RunResult(
        run_id="run-blocked",
        workflow_id="daily",
        workflow_version="1",
        status=WorkflowStatus.BLOCKED,
        output={
            "blocked_report": BlockedReport(
                title="Blocked Daily",
                reasons=["quality gate blocked"],
                draft={"title": "Draft"},
            ),
            "report_markdown": "# Blocked\n",
            "report_quality_summary": ReportQualitySummary(
                quality_score=0.35,
                support_coverage=0.2,
                citation_passed=False,
                decision="block",
            ),
        },
        error={"error_type": "QualityGateBlocked", "message": "quality gate blocked"},
        manifest_path="runs/run-blocked/manifest.json",
    )

    record = report_record_from_result(result)

    assert record is not None
    assert record.report_id == "run-blocked:blocked"
    assert record.status == "blocked"
    assert record.title == "Blocked Daily"
    assert record.report_json["reasons"] == ["quality gate blocked"]
    assert record.quality_score == 0.35


def test_local_json_persistence_adapter_writes_records(tmp_path) -> None:
    repository = LocalJsonPersistenceAdapter(tmp_path)

    repository.save_workflow_run(
        WorkflowRunRecord(
            run_id="run-1",
            workflow_id="daily",
            workflow_version="1",
            status="succeeded",
            profile="live-offline",
            metrics={"quality_score": 1.0},
        )
    )
    repository.save_report(
        ReportRecord(
            report_id="run-1:final",
            run_id="run-1",
            status="final",
            title="Daily",
            quality_score=1.0,
            citation_coverage_score=1.0,
        )
    )

    workflow_path = tmp_path / "_records" / "workflow_runs" / "run-1.json"
    report_path = tmp_path / "_records" / "reports" / "run-1_final.json"
    assert workflow_path.exists()
    assert report_path.exists()
    assert json.loads(workflow_path.read_text(encoding="utf-8"))["run_id"] == "run-1"
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["report_id"] == "run-1:final"
    assert report_payload["citation_coverage_score"] == 1.0


def test_local_json_persistence_adapter_preserves_record_when_write_fails(
    tmp_path,
    monkeypatch,
) -> None:
    repository = LocalJsonPersistenceAdapter(tmp_path)
    repository.save_workflow_run(
        WorkflowRunRecord(
            run_id="run-1",
            workflow_id="daily",
            workflow_version="1",
            status="succeeded",
            profile="live-offline",
        )
    )
    workflow_path = tmp_path / "_records" / "workflow_runs" / "run-1.json"
    original_payload = json.loads(workflow_path.read_text(encoding="utf-8"))

    def fail_after_partial_write(payload, handle, **kwargs):
        handle.write('{"partial":')
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr("storage.repository.json.dump", fail_after_partial_write)

    with pytest.raises(RuntimeError, match="simulated write failure"):
        repository.save_workflow_run(
            WorkflowRunRecord(
                run_id="run-1",
                workflow_id="daily",
                workflow_version="1",
                status="failed",
                profile="live-offline",
            )
        )

    assert json.loads(workflow_path.read_text(encoding="utf-8")) == original_payload
    assert list(workflow_path.parent.glob(".run-1.json.*.tmp")) == []


def test_run_result_extracts_source_evidence_claim_and_quality_records() -> None:
    result = _storage_run_result()

    source_records = source_item_records_from_result(result)
    evidence_records = evidence_item_records_from_result(result)
    claim_records = claim_records_from_result(result)
    quality_record = quality_result_record_from_result(result)

    assert source_records[0].source_item_id == "raw-1"
    assert evidence_records[0].evidence_id == "ev-1"
    assert evidence_records[0].source_item_ids == ["raw-1"]
    assert claim_records[0].status == "accepted"
    assert claim_records[0].supporting_sources == ["https://example.com/a"]
    assert quality_record is not None
    assert quality_record.decision == "pass"
    assert quality_record.claim_support_score == 1.0


def test_run_persistence_batch_from_result_collects_final_state_records() -> None:
    batch = run_persistence_batch_from_result(_storage_run_result(), profile="live-offline")

    assert isinstance(batch, RunPersistenceBatch)
    assert batch.workflow_run.run_id == "run-1"
    assert batch.report is None
    assert batch.source_items[0].source_item_id == "raw-1"
    assert batch.evidence_items[0].evidence_id == "ev-1"
    assert batch.claims[0].supporting_evidence_ids == ["ev-1"]
    assert batch.quality_result is not None
    assert batch.quality_result.quality_result_id == "run-1:quality"


def test_persist_run_result_uses_repository_batch_boundary_when_available() -> None:
    repository = _BatchRepository()

    persist_run_result(repository, _storage_run_result(), profile="live-offline")

    assert repository.migrated is True
    assert len(repository.batches) == 1
    assert repository.batches[0].workflow_run.run_id == "run-1"
    assert repository.individual_writes == []


def test_local_json_persistence_adapter_writes_final_state_records(tmp_path) -> None:
    repository = LocalJsonPersistenceAdapter(tmp_path)

    persist_run_result(repository, _storage_run_result(), profile="live-offline")

    assert repository.list_source_items("run-1")[0]["source_item_id"] == "raw-1"
    assert repository.list_evidence_items("run-1")[0]["evidence_id"] == "ev-1"
    assert repository.list_claims("run-1")[0]["claim_id"] == "claim-1"
    assert repository.list_quality_results("run-1")[0]["quality_result_id"] == "run-1:quality"


def test_local_json_persistence_adapter_writes_individual_final_state_records(tmp_path) -> None:
    repository = LocalJsonPersistenceAdapter(tmp_path)

    repository.save_source_item(
        SourceItemRecord(
            source_item_id="raw-1",
            run_id="run-1",
            source_id="source",
            title="Title",
            url="https://example.com/a",
        )
    )
    repository.save_evidence_item(
        EvidenceItemRecord(
            evidence_id="ev-1",
            run_id="run-1",
            claim="Title",
            summary="Summary",
            source_urls=["https://example.com/a"],
            source_item_ids=["raw-1"],
            confidence=0.9,
        )
    )
    repository.save_claim(
        ClaimRecord(claim_id="claim-1", run_id="run-1", status="accepted", text="Title")
    )
    repository.save_quality_result(
        QualityResultRecord(
            quality_result_id="run-1:quality",
            run_id="run-1",
            decision="pass",
            passed=True,
            quality_score=1.0,
        )
    )

    assert len(repository.list_source_items("run-1")) == 1
    assert len(repository.list_evidence_items("run-1")) == 1
    assert len(repository.list_claims("run-1")) == 1
    assert len(repository.list_quality_results("run-1")) == 1


def test_local_json_persistence_adapter_skips_bad_record_json(tmp_path) -> None:
    repository = LocalJsonPersistenceAdapter(tmp_path)
    repository.save_source_item(
        SourceItemRecord(
            source_item_id="raw-1",
            run_id="run-1",
            source_id="source",
            title="Title",
            url="https://example.com/a",
        )
    )
    bad_path = tmp_path / "_records" / "source_items" / "run-1" / "bad.json"
    bad_path.write_text("{bad", encoding="utf-8")

    records = repository.list_source_items("run-1")

    assert [record["source_item_id"] for record in records] == ["raw-1"]


def test_local_json_persistence_adapter_rejects_unsafe_run_id_on_reads(tmp_path) -> None:
    repository = LocalJsonPersistenceAdapter(tmp_path)

    with pytest.raises(ValueError, match="invalid run_id"):
        repository.list_source_items("../secret")

    with pytest.raises(ValueError, match="invalid run_id"):
        repository.list_evidence_items("../secret")

    with pytest.raises(ValueError, match="invalid run_id"):
        repository.list_claims("../secret")

    with pytest.raises(ValueError, match="invalid run_id"):
        repository.list_quality_results("../secret")


class _BatchRepository:
    def __init__(self) -> None:
        self.migrated = False
        self.batches: list[RunPersistenceBatch] = []
        self.individual_writes: list[str] = []

    def migrate(self) -> None:
        self.migrated = True

    def save_run_records(self, batch: RunPersistenceBatch) -> None:
        self.batches.append(batch)

    def save_workflow_run(self, record) -> None:
        self.individual_writes.append("workflow_run")

    def save_report(self, record) -> None:
        self.individual_writes.append("report")


def _storage_run_result() -> RunResult:
    evidence_bundle = EvidenceBundle(
        bundle_id="daily",
        items=[
            EvidenceItem(
                evidence_id="ev-1",
                source_url="https://example.com/a",
                title="AI policy update",
                summary="Policy summary.",
                confidence=0.9,
                source_id="source",
                metadata={"source_lineage": {"source_item_id": "raw-1"}},
            )
        ],
    )
    return RunResult(
        run_id="run-1",
        workflow_id="daily",
        workflow_version="1",
        status=WorkflowStatus.SUCCEEDED,
        output={
            "raw_items": [
                {
                    "source_item_id": "raw-1",
                    "source_id": "source",
                    "title": "AI policy update",
                    "url": "https://example.com/a",
                    "fetched_at": "2026-05-11T00:00:00Z",
                    "summary": "Policy summary.",
                    "metadata": {"source_reliability": "high"},
                }
            ],
            "evidence_bundle": evidence_bundle,
            "verified_findings": VerifiedFindings(
                accepted_claims=[
                    VerifiedClaim(
                        claim_id="claim-1",
                        claim="AI policy update",
                        status="accepted",
                        confidence=0.9,
                        supporting_evidence_ids=["ev-1"],
                        supporting_sources=["https://example.com/a"],
                    )
                ]
            ),
            "report_quality_summary": ReportQualitySummary(
                quality_score=1.0,
                support_coverage=1.0,
                citation_passed=True,
                decision="pass",
                claim_support_score=1.0,
                evidence_alignment_score=1.0,
            ),
        },
        manifest_path="runs/run-1/manifest.json",
    )
