import json
from datetime import UTC, datetime
from enum import Enum
from dataclasses import dataclass

import pytest

from business.foundation.models.report_output import BlockedReport, FinalReport
from business.layers.relation.evidence import EvidenceBundle, EvidenceItem, VerifiedClaim, VerifiedFindings
from business.layers.analysis.quality import QualityGateMetrics, ReportQualitySummary
from infrastructure.storage.records import (
    ClaimRecord,
    EvidenceItemRecord,
    QualityResultRecord,
    ReportDetailRecord,
    ReportSummaryRecord,
    SourceItemRecord,
)
from infrastructure.storage.persistence import (
    LocalJsonPersistenceAdapter,
    ReportRecord,
    RunPersistenceBatch,
    RunPersistenceInput,
    GraphRunRecord,
    claim_records_from_result,
    evidence_item_records_from_result,
    persist_run_input,
    persist_run_result,
    quality_result_record_from_result,
    report_record_from_result,
    run_persistence_batch_from_input,
    run_persistence_batch_from_result,
    run_persistence_input_from_output,
    run_persistence_input_from_result,
    source_item_records_from_result,
    graph_run_record_from_result,
)


class _Status(str, Enum):
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"


@dataclass
class _GraphResult:
    run_id: str
    graph_id: str
    graph_version: str
    status: _Status
    output: dict
    artifact_dir: str | None = None
    manifest_path: str | None = None
    events_path: str | None = None
    error: dict | None = None


def test_storage_record_contracts_roundtrip_with_stable_dict_output() -> None:
    fetched_at = datetime(2026, 5, 11, 0, 0, tzinfo=UTC)
    created_at = datetime(2026, 5, 11, 1, 0, tzinfo=UTC)
    source = SourceItemRecord(
        source_item_id="source-item-1",
        run_id="run-1",
        source_id="rss-openai",
        title="Source title",
        url="https://example.com/source",
        canonical_url="https://example.com/canonical",
        published_at=fetched_at,
        fetched_at=fetched_at,
        raw_artifact_id="artifact-raw-1",
        metadata={"topic": "ai"},
    )
    evidence = EvidenceItemRecord(
        evidence_id="evidence-1",
        run_id="run-1",
        claim="Claim text",
        summary="Evidence summary",
        source_urls=["https://example.com/source"],
        source_item_ids=["source-item-1"],
        confidence=0.87,
        lineage_json={"source_item_id": "source-item-1"},
        metadata={"category": "policy"},
    )
    quality = QualityResultRecord(
        quality_result_id="quality-1",
        run_id="run-1",
        decision="pass",
        passed=True,
        quality_score=0.91,
        citation_coverage_score=0.8,
        claim_support_score=0.75,
        evidence_alignment_score=0.7,
        payload={"details": {"passed": True}},
        created_at=created_at,
    )

    assert SourceItemRecord.from_dict(source.to_dict()).to_dict() == source.to_dict()
    assert EvidenceItemRecord.from_dict(evidence.to_dict()).to_dict() == evidence.to_dict()
    assert QualityResultRecord.from_dict(quality.to_dict()).to_dict() == quality.to_dict()
    assert set(source.to_dict()) >= {
        "source_id",
        "source_item_id",
        "url",
        "canonical_url",
        "published_at",
        "fetched_at",
        "raw_artifact_id",
    }
    assert set(evidence.to_dict()) >= {
        "evidence_id",
        "source_item_ids",
        "source_urls",
        "confidence",
        "lineage_json",
    }
    assert set(quality.to_dict()) >= {"decision", "passed", "payload"}


def test_claim_record_contract_supports_review_statuses_roundtrip() -> None:
    for status in ["accepted", "rejected", "uncertain"]:
        claim = ClaimRecord(
            claim_id=f"claim-{status}",
            run_id="run-1",
            status=status,
            text="Claim text",
            confidence=0.5,
            supporting_evidence_ids=["ev-support"],
            rejecting_evidence_ids=["ev-reject"],
            payload={"status": status},
            created_at=datetime(2026, 5, 11, 1, 0, tzinfo=UTC),
        )

        assert ClaimRecord.from_dict(claim.to_dict()).to_dict() == claim.to_dict()


def test_graph_and_report_record_contracts_roundtrip_with_stable_dict_output() -> None:
    graph = GraphRunRecord(
        run_id="run-1",
        graph_id="daily.graph",
        graph_version="1",
        status="succeeded",
        profile="live-offline",
        artifact_dir="runs/run-1",
        manifest_path="runs/run-1/manifest.json",
        events_path="runs/run-1/events.jsonl",
        error={"type": "none"},
        metrics={"quality_score": 0.9},
    )
    report = ReportRecord(
        report_id="run-1:final",
        run_id="run-1",
        status="final",
        title="Daily",
        report_json={"title": "Daily"},
        report_markdown="# Daily\n",
        quality_score=0.9,
        citation_coverage_score=0.8,
        manifest_path="runs/run-1/manifest.json",
    )

    assert GraphRunRecord.from_dict(graph.to_dict()).to_dict() == graph.to_dict()
    assert ReportRecord.from_dict(report.to_dict()).to_dict() == report.to_dict()
    assert set(graph.to_dict()) >= {
        "run_id",
        "graph_id",
        "graph_version",
        "status",
        "profile",
        "artifact_dir",
        "manifest_path",
        "events_path",
        "error",
        "metrics",
    }
    assert set(report.to_dict()) >= {
        "report_id",
        "run_id",
        "status",
        "title",
        "report_json",
        "report_markdown",
        "quality_score",
        "citation_coverage_score",
        "manifest_path",
    }


def test_graph_run_record_rejects_legacy_identity_payload() -> None:
    with pytest.raises(ValueError, match="legacy_workflow_identity_not_supported"):
        GraphRunRecord.from_dict(
            {
                "run_id": "run-1",
                "workflow_id": "daily",
                "workflow_version": "1",
                "status": "succeeded",
            }
        )




def test_local_json_persistence_adapter_report_reads_return_canonical_contract(tmp_path) -> None:
    repository = LocalJsonPersistenceAdapter(tmp_path)
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    (run_dir / "report.json").write_text(json.dumps({"title": "Daily"}), encoding="utf-8")
    (run_dir / "report.md").write_text("# Daily\n", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "graph_id": "daily.graph",
                "graph_version": "1",
                "status": "succeeded",
                "finished_at": "2026-05-11T00:00:00Z",
                "quality_score": 0.9,
                "artifacts": {"report_json": "report.json", "report_markdown": "report.md"},
            }
        ),
        encoding="utf-8",
    )

    detail = repository.get_report("run-1:final")
    summary = repository.list_reports(limit=10)[0]

    assert isinstance(detail, ReportDetailRecord)
    assert isinstance(summary, ReportSummaryRecord)
    assert detail.report_id == "run-1:final"
    assert summary.report_id == "run-1:final"
    assert detail.to_dict()["report_json"]["title"] == "Daily"
    assert summary.to_dict()["graph_id"] == "daily.graph"
    result = _GraphResult(
        run_id="run-1",
        graph_id="daily.graph",
        graph_version="1",
        status=_Status.SUCCEEDED,
        output={
            "report_quality_summary": ReportQualitySummary(
                quality_score=0.9,
                support_coverage=1.0,
                citation_passed=True,
                accepted_claims_count=2,
                rejected_claims_count=0,
                uncertain_claims_count=0,
                unsupported_claims_count=0,
                high_severity_unsupported_claims_count=0,
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

    record = graph_run_record_from_result(result, profile="live-offline")

    assert record.run_id == "run-1"
    assert record.status == "succeeded"
    assert record.profile == "live-offline"
    assert record.metrics["report_quality_summary"]["quality_score"] == 0.9
    assert record.metrics["quality_gate_metrics"]["citation_coverage_score"] == 0.75


def test_report_record_from_result_extracts_final_report() -> None:
    result = _GraphResult(
        run_id="run-1",
        graph_id="daily.graph",
        graph_version="1",
        status=_Status.SUCCEEDED,
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
                accepted_claims_count=1,
                rejected_claims_count=0,
                uncertain_claims_count=0,
                unsupported_claims_count=0,
                high_severity_unsupported_claims_count=0,
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
    assert record.report_json["quality_trace"]["decision"] == "blocked"
    assert record.report_json["quality_trace"]["unsupported_sections"] == []


def test_record_builders_extract_report_and_quality_records_from_projected_daily_output() -> None:
    result = _GraphResult(
        run_id="run-projected",
        graph_id="daily.graph",
        graph_version="1",
        status=_Status.SUCCEEDED,
        output={
            "final_report": FinalReport(
                title="Projected Daily",
                sections=[{"title": "Summary", "content": "Supported daily update."}],
                source_urls=["https://example.com/a"],
                metadata={"evidence_bundle_id": "bundle-1"},
            ),
            "report_markdown": "# Projected Daily\n",
            "report_quality_summary": ReportQualitySummary(
                quality_score=0.88,
                support_coverage=0.9,
                citation_passed=True,
                citation_coverage_score=0.82,
                claim_support_score=0.76,
                evidence_alignment_score=0.8,
                accepted_claims_count=2,
                rejected_claims_count=1,
                uncertain_claims_count=1,
                unsupported_claims_count=1,
                high_severity_unsupported_claims_count=0,
                passed=True,
                decision="pass",
            ),
            "quality_result": {
                "decision": "pass",
                "passed": True,
                "route": "final",
                "quality_score": 0.9,
                "citation_coverage_score": 0.84,
                "claim_support_score": 0.78,
                "evidence_alignment_score": 0.81,
                "metadata": {
                    "citation_failure_categories": ["missing_citation"],
                    "remediation": ["add cited source"],
                    "reviewer_trace": {"editor": "accepted"},
                    "accepted_claims_count": 2,
                    "rejected_claims_count": 1,
                    "uncertain_claims_count": 1,
                    "unsupported_claims_count": 1,
                },
            },
            "citation_check_result": {
                "citation_coverage_score": 0.7,
                "claim_support_score": 0.75,
                "unsupported_claims": ["unsupported claim"],
                "rejected_claim_usage": ["rejected source used"],
            },
            "support_matrix": {"unsupported_sections": ["Summary"]},
            "quality_gate_metrics": QualityGateMetrics(
                evidence_items_count=3,
                unsupported_urls_count=1,
                missing_section_sources_count=0,
                unsupported_sections_count=1,
                blocked=False,
                decision="pass",
                citation_coverage_score=0.91,
                support_coverage=0.9,
                quality_score=0.88,
                accepted_claims_count=2,
                rejected_claims_count=1,
                uncertain_claims_count=1,
                unsupported_claims_count=1,
                claim_support_score=0.78,
            ),
        },
        manifest_path="runs/run-projected/manifest.json",
    )

    input_model = run_persistence_input_from_result(result, profile="live-offline")
    batch = run_persistence_batch_from_input(input_model)

    assert isinstance(input_model, RunPersistenceInput)
    assert input_model.run_id == "run-projected"
    assert input_model.profile == "live-offline"
    assert input_model.final_report is result.output["final_report"]
    assert input_model.quality_gate_metrics is result.output["quality_gate_metrics"]
    assert batch.report is not None
    assert batch.quality_result is not None
    assert batch.report.report_id == "run-projected:final"
    assert batch.report.quality_score == 0.88
    assert batch.report.citation_coverage_score == 0.91
    assert batch.report.report_json["quality_trace"] == {
        "decision": "pass",
        "route": "final",
        "citation_failure_categories": ["missing_citation"],
        "unsupported_claims": ["unsupported claim"],
        "rejected_claim_usage": ["rejected source used"],
        "unsupported_sections": ["Summary"],
        "remediation": ["add cited source"],
        "reviewer_trace": {"editor": "accepted"},
        "accepted_claims_count": 2,
        "rejected_claims_count": 1,
        "uncertain_claims_count": 1,
        "unsupported_claims_count": 1,
        "evidence_bundle_id": "bundle-1",
    }
    assert batch.graph_run.metrics["report_quality_summary"]["decision"] == "pass"
    assert batch.quality_result.decision == "pass"
    assert batch.quality_result.quality_score == 0.9
    assert batch.quality_result.citation_coverage_score == 0.84
    assert batch.quality_result.claim_support_score == 0.78
    assert batch.quality_result.evidence_alignment_score == 0.81
    assert batch.quality_result.payload["quality_summary"]["quality_score"] == 0.88
    assert batch.quality_result.payload["citation_check"]["unsupported_claims"] == [
        "unsupported claim"
    ]


def test_run_persistence_input_from_output_consumes_projected_view_without_mutating_result() -> None:
    final_report = FinalReport(
        title="Projected Daily",
        sections=[],
        source_urls=[],
    )
    result = _GraphResult(
        run_id="run-output-view",
        graph_id="daily.graph",
        graph_version="1",
        status=_Status.SUCCEEDED,
        output={"report.final": final_report},
    )

    input_model = run_persistence_input_from_output(
        result,
        {"final_report": final_report},
        profile="live-offline",
    )

    assert "final_report" not in result.output
    assert input_model.final_report is final_report
    assert input_model.profile == "live-offline"


def test_run_persistence_input_requires_graph_identity() -> None:
    result = type(
        "Result",
        (),
        {
            "run_id": "run-without-graph",
            "status": _Status.SUCCEEDED,
            "output": {},
            "artifact_dir": None,
            "manifest_path": None,
            "events_path": None,
            "error": None,
        },
    )()

    with pytest.raises(ValueError, match="graph identity is required"):
        run_persistence_input_from_result(result)


def test_report_record_from_result_preserves_blocked_report_status() -> None:
    result = _GraphResult(
        run_id="run-blocked",
        graph_id="daily.graph",
        graph_version="1",
        status=_Status.BLOCKED,
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
    assert record.report_json["quality_trace"]["route"] is None
    assert record.quality_score == 0.35


def test_local_json_persistence_adapter_writes_records(tmp_path) -> None:
    repository = LocalJsonPersistenceAdapter(tmp_path)

    repository.save_graph_run(
        GraphRunRecord(
            run_id="run-1",
            graph_id="daily.graph",
            graph_version="1",
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

    workflow_path = tmp_path / "_records" / "graph_runs" / "run-1.json"
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
    repository.save_graph_run(
        GraphRunRecord(
            run_id="run-1",
            graph_id="daily.graph",
            graph_version="1",
            status="succeeded",
            profile="live-offline",
        )
    )
    workflow_path = tmp_path / "_records" / "graph_runs" / "run-1.json"
    original_payload = json.loads(workflow_path.read_text(encoding="utf-8"))

    def fail_after_partial_write(payload, handle, **kwargs):
        handle.write('{"partial":')
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(
        "infrastructure.storage.persistence.local_json_adapter.json.dump",
        fail_after_partial_write,
    )

    with pytest.raises(RuntimeError, match="simulated write failure"):
        repository.save_graph_run(
            GraphRunRecord(
                run_id="run-1",
                graph_id="daily.graph",
                graph_version="1",
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
    assert batch.graph_run.run_id == "run-1"
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
    assert repository.batches[0].graph_run.run_id == "run-1"
    assert repository.individual_writes == []


def test_persist_run_input_uses_explicit_record_input_boundary() -> None:
    repository = _BatchRepository()
    input_model = run_persistence_input_from_result(_storage_run_result(), profile="live-offline")

    persist_run_input(repository, input_model)

    assert repository.migrated is True
    assert len(repository.batches) == 1
    assert repository.batches[0].graph_run.run_id == "run-1"
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

    def save_graph_run(self, record) -> None:
        self.individual_writes.append("graph_run")

    def save_report(self, record) -> None:
        self.individual_writes.append("report")


def _storage_run_result() -> _GraphResult:
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
    return _GraphResult(
        run_id="run-1",
        graph_id="daily.graph",
        graph_version="1",
        status=_Status.SUCCEEDED,
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
