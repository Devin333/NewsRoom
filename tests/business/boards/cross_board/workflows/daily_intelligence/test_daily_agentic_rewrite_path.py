from __future__ import annotations

from framework.specs import WorkflowStatus
from business.boards.cross_board.workflows.daily_intelligence import AgenticDailyIntelligenceRunner
from business.boards.cross_board.workflows.daily_intelligence.agent_fixtures import (
    DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_INVALID_SOURCE,
    DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_MISSING_EDIT,
    DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_VALID,
)
from business.boards.cross_board.workflows.daily_intelligence.profiles import PROFILE_AGENTIC_OFFLINE


def test_agentic_rewrite_required_with_valid_edited_draft_succeeds(tmp_path) -> None:
    result = AgenticDailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile=PROFILE_AGENTIC_OFFLINE,
        topic="AI policy",
        source_limit=1,
        run_id="agentic-rewrite-valid",
        agent_fixture_scenario=DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_VALID,
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["report_draft"]["title"] == "Daily Intelligence: AI policy"
    assert result.output["editor_review"]["decision"] == "rewrite_required"
    assert result.output["quality_result"]["passed"] is True
    assert result.output["quality_result"]["decision"] == "pass"
    assert result.output["quality_result"]["route"] == "final"
    assert result.output["quality_result"]["rewrite_attempts"] == 0
    assert result.output["quality_gate_metrics"]["rewrite_attempts"] == 0
    assert result.output["final_report"].metadata["rewrite_attempts"] == 0
    assert any(
        event.event_type == "finalize_report_bypassed_non_social_media"
        for event in result.output["quality_events"]
    )
    assert "blocked_report" not in result.output


def test_agentic_rewrite_required_with_invalid_source_blocks(tmp_path) -> None:
    result = AgenticDailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile=PROFILE_AGENTIC_OFFLINE,
        topic="AI policy",
        source_limit=1,
        run_id="agentic-rewrite-invalid-source",
        agent_fixture_scenario=DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_INVALID_SOURCE,
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["report_draft"]["title"] == "Daily Intelligence: AI policy"
    assert result.output["editor_review"]["decision"] == "rewrite_required"
    assert result.output["quality_result"]["passed"] is True
    assert result.output["quality_result"]["decision"] == "pass"
    assert result.output["quality_result"]["route"] == "final"
    assert result.output["quality_gate_metrics"]["rewrite_required"] is False
    assert "final_report" in result.output
    assert "blocked_report" not in result.output
    assert any(
        event.event_type == "finalize_report_bypassed_non_social_media"
        for event in result.output["quality_events"]
    )


def test_agentic_rewrite_required_without_edited_draft_blocks(tmp_path) -> None:
    result = AgenticDailyIntelligenceRunner(artifact_root=tmp_path).run(
        profile=PROFILE_AGENTIC_OFFLINE,
        topic="AI policy",
        source_limit=1,
        run_id="agentic-rewrite-missing-edit",
        agent_fixture_scenario=DAILY_AGENT_FIXTURE_SCENARIO_REWRITE_MISSING_EDIT,
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["report_draft"]["title"] == "Daily Intelligence: AI policy"
    assert result.output["editor_review"]["decision"] == "rewrite_required"
    assert result.output["edited_report_draft"] is None
    assert result.output["quality_result"]["passed"] is True
    assert result.output["quality_result"]["decision"] == "pass"
    assert result.output["quality_result"]["route"] == "final"
    assert result.output["quality_gate_metrics"]["rewrite_required"] is False
    assert "blocked_report" not in result.output
    assert "final_report" in result.output
