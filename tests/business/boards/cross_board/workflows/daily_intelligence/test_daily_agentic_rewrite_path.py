from __future__ import annotations

from framework.specs import WorkflowStatus
from business.boards.cross_board.workflows.daily_intelligence import AgenticDailyIntelligenceRunner
from business.boards.cross_board.workflows.daily_intelligence.profiles import PROFILE_AGENTIC_OFFLINE


def test_agentic_rewrite_required_with_valid_edited_draft_succeeds(tmp_path) -> None:
    result = AgenticDailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile=PROFILE_AGENTIC_OFFLINE,
        topic="AI policy rewrite-valid",
        source_limit=1,
        run_id="agentic-rewrite-valid",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["editor_review"]["decision"] == "rewrite_required"
    assert result.output["quality_result"]["passed"] is True
    assert result.output["quality_result"]["route"] == "rewrite"
    assert result.output["quality_result"]["rewrite_attempts"] == 1
    assert result.output["quality_gate_metrics"]["rewrite_attempts"] == 1
    assert result.output["final_report"].metadata["rewrite_attempts"] == 1
    assert "Edited summary" in result.output["report_markdown"]
    assert "blocked_report" not in result.output


def test_agentic_rewrite_required_with_invalid_source_blocks(tmp_path) -> None:
    result = AgenticDailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile=PROFILE_AGENTIC_OFFLINE,
        topic="AI policy rewrite-invalid-source",
        source_limit=1,
        run_id="agentic-rewrite-invalid-source",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["editor_review"]["decision"] == "rewrite_required"
    assert result.output["quality_result"]["passed"] is False
    assert result.output["quality_result"]["route"] == "blocked"
    assert result.output["quality_gate_metrics"]["rewrite_required"] is True
    assert result.output["blocked_report"].metadata["quality_route"] == "blocked"
    assert "final_report" not in result.output
    assert "report_markdown" not in result.output
    assert any(
        "outside evidence bundle" in reason
        for reason in result.output["blocked_report"].reasons
    )


def test_agentic_rewrite_required_without_edited_draft_blocks(tmp_path) -> None:
    result = AgenticDailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile=PROFILE_AGENTIC_OFFLINE,
        topic="AI policy rewrite-missing-edit",
        source_limit=1,
        run_id="agentic-rewrite-missing-edit",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["editor_review"]["decision"] == "rewrite_required"
    assert result.output["edited_report_draft"] is None
    assert result.output["quality_result"]["passed"] is False
    assert result.output["quality_result"]["route"] == "blocked"
    assert result.output["quality_gate_metrics"]["rewrite_required"] is True
    assert "blocked_report" in result.output
    assert "final_report" not in result.output
