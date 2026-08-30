from backend.layers._worker_utils import handler_output, report_status_from_result
from backend.layers.worker_output import (
    WorkerOutputEnvelope,
    WorkerReportPayload,
    report_status_from_output,
    summary_from_output,
)


def test_worker_report_payload_extracts_blocked_status_without_status_field() -> None:
    report = WorkerReportPayload.from_mapping(
        {"blocked_report": {"title": "Blocked", "reasons": ["quality"]}}
    )

    assert report.source_key == "blocked_report"
    assert report.status == "blocked"
    assert report.summary == {"title": "Blocked"}


def test_worker_report_payload_extracts_namespaced_blocked_status() -> None:
    report = WorkerReportPayload.from_mapping(
        {"report.blocked": {"title": "Blocked", "reasons": ["quality"]}}
    )

    assert report.source_key == "report.blocked"
    assert report.status == "blocked"
    assert report.summary == {"title": "Blocked"}


def test_worker_report_status_reads_namespaced_report_metadata_status() -> None:
    output = {"report.metadata": {"title": "Daily", "report_status": "ready"}}

    assert report_status_from_output(output) == "ready"
    assert summary_from_output(output) == {"title": "Daily", "report_status": "ready"}


def test_worker_report_payload_reads_legacy_report_metadata_status() -> None:
    output = {"report_metadata": {"title": "Daily", "report_status": "ready"}}

    assert report_status_from_output(output) == "ready"
    assert summary_from_output(output) == {"title": "Daily", "report_status": "ready"}


def test_worker_report_status_preserves_blocked_fallback_when_report_has_no_status() -> None:
    output = {
        "report": {"title": "Draft"},
        "blocked_report": {"title": "Blocked"},
    }

    assert report_status_from_output(output) == "blocked"
    assert summary_from_output(output) == {"title": "Draft"}


def test_worker_report_status_preserves_namespaced_blocked_fallback() -> None:
    output = {
        "report.final": {"title": "Draft"},
        "report.blocked": {"title": "Blocked"},
    }

    assert report_status_from_output(output) == "blocked"
    assert summary_from_output(output) == {"title": "Draft"}


def test_worker_output_envelope_adds_run_id_and_formal_summary() -> None:
    output = WorkerOutputEnvelope.from_payload(
        {"output": {"report": {"title": "Run report", "status": "published"}}},
        run_id="run-1",
    ).to_dict()

    assert output["run_id"] == "run-1"
    assert output["artifact_dir"] is None
    assert output["summary"] == {"title": "Run report", "status": "published"}


def test_worker_utils_keep_legacy_handler_output_contract() -> None:
    output = handler_output(
        {"output": {"summary": "Daily summary"}},
        run_id="run-2",
    )

    assert output["run_id"] == "run-2"
    assert output["summary"] == {"text": "Daily summary"}


def test_worker_utils_report_status_reads_result_output_contract() -> None:
    class Result:
        output = {"blocked_report": {"title": "Blocked"}}

    assert report_status_from_result(Result()) == "blocked"
