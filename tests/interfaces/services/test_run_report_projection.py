from __future__ import annotations

from interfaces.services.run_report_projection import project_run_report_for_interface


def test_project_run_report_for_interface_reads_blocked_report_output() -> None:
    output = {"blocked_report": {"title": "Blocked"}}

    projection = project_run_report_for_interface(
        {
            "workflow_id": "research-paper-analysis",
            "run_id": "run-1",
            "output": output,
        }
    )

    assert projection.output == output
    assert projection.output is not output
    assert projection.report_status == "blocked"
    assert projection.report_id == "run-1:blocked"
    assert "blocked_report" in projection.output
    assert output == {"blocked_report": {"title": "Blocked"}}


def test_project_run_report_for_interface_keeps_non_daily_canonical_report_output() -> None:
    output = {"final_report": {"title": "Weekly"}}

    projection = project_run_report_for_interface(
        {
            "workflow_id": "weekly-intelligence",
            "run_id": "run-weekly",
            "output": output,
        }
    )

    assert projection.output == output
    assert projection.output is not output
    assert projection.report_status == "final"
    assert projection.report_id == "run-weekly:final"


def test_project_run_report_for_interface_prefers_explicit_report_id() -> None:
    projection = project_run_report_for_interface(
        {
            "workflow_id": "weekly-intelligence",
            "run_id": "run-weekly",
            "output": {
                "final_report_id": "report-123",
                "final_report": {"title": "Weekly"},
            },
        }
    )

    assert projection.report_status == "final"
    assert projection.report_id == "report-123"
