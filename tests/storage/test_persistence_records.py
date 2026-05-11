from core.framework.run_result import RunResult
from core.framework.specs import WorkflowStatus
from domain.reports import FinalReport
from quality import QualityGateMetrics, ReportQualitySummary
from storage.repository import (
    report_record_from_result,
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
