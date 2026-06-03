from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.profiles import LEGACY_DAILY_WORKFLOW_ID
from interfaces.services.daily_interface_projection import project_run_output_for_interface


def test_project_run_output_for_interface_adds_daily_public_aliases() -> None:
    output = {"report.blocked": {"title": "Blocked"}}
    projected = project_run_output_for_interface(
        {
            "workflow_id": LEGACY_DAILY_WORKFLOW_ID,
            "output": output,
        }
    )

    assert projected is not output
    assert projected["blocked_report"] == {"title": "Blocked"}
    assert output == {"report.blocked": {"title": "Blocked"}}


def test_project_run_output_for_interface_keeps_non_daily_output_unchanged() -> None:
    output = {"report.final": {"title": "Weekly"}}

    projected = project_run_output_for_interface(
        {
            "workflow_id": "weekly-intelligence",
            "output": output,
        }
    )

    assert projected is output
    assert "final_report" not in projected
