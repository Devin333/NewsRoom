from __future__ import annotations

import pytest

from business.boards._workflow_runtime import (
    BoardWorkflowExecution,
    WorkflowRecoveryAction,
    WorkflowStageStatus,
    skipped_stage_result,
    stage_result,
)
from business.boards.ai_news.workflow import AINewsWorkflow
from tests.business.final_runtime_fixtures import sample_raw_items


def test_successful_board_workflow_records_stage_outcomes() -> None:
    result = AINewsWorkflow().run(sample_raw_items())
    execution = result.metadata["workflow_execution"]

    assert result.metadata["stage_count"] == len(result.metadata["stages"])
    assert result.metadata["failed_stage_count"] == 0
    assert execution["status"] in {WorkflowStageStatus.SUCCESS.value, WorkflowStageStatus.WARNING.value}
    assert [stage["stage_name"] for stage in execution["stages"]] == result.metadata["stages"]
    assert all(stage["duration_ms"] >= 0.0 for stage in execution["stages"])
    assert execution["stages"][0]["stage_name"] == "resolve_context"


def test_empty_workflow_input_records_warning_stage() -> None:
    result = AINewsWorkflow().run([])
    execution = result.metadata["workflow_execution"]
    warning_stages = [
        stage
        for stage in execution["stages"]
        if stage["status"] == WorkflowStageStatus.WARNING.value
    ]

    assert result.metadata["warning_stage_count"] >= 1
    assert warning_stages
    assert any("no signals" in " ".join(stage["warnings"]) or "no cards" in " ".join(stage["warnings"]) for stage in warning_stages)


def test_failed_workflow_stage_is_recorded_and_exception_is_reraised() -> None:
    workflow = _FailingWorkflow()

    with pytest.raises(RuntimeError, match="pipeline failed"):
        workflow.run(sample_raw_items())

    assert workflow.last_execution is not None
    failed_stages = [
        stage
        for stage in workflow.last_execution.stages
        if stage.status == WorkflowStageStatus.FAILED
    ]
    assert failed_stages
    assert failed_stages[0].stage_name == "run_pipeline"
    assert failed_stages[0].error_type == "RuntimeError"
    assert failed_stages[0].recovery_action == WorkflowRecoveryAction.BLOCK
    assert workflow.last_execution.failed_stage_count == 1


def test_workflow_stage_status_supports_skipped() -> None:
    skipped = skipped_stage_result(
        "optional_enrichment",
        reason="optional stage disabled",
        metadata={"feature": "enrichment"},
    )
    execution = BoardWorkflowExecution(workflow_id="wf", board_type="ai_news").add_stage(skipped).finish()

    assert skipped.status == WorkflowStageStatus.SKIPPED
    assert skipped.recovery_action == WorkflowRecoveryAction.SKIP
    assert skipped.warnings == ["optional stage disabled"]
    assert skipped.metadata["feature"] == "enrichment"
    assert execution.status == WorkflowStageStatus.SKIPPED
    assert execution.to_dict()["stages"][0]["status"] == "skipped"


def test_failed_stage_duration_uses_current_stage_start_time() -> None:
    workflow = _SlowFailingWorkflow()

    with pytest.raises(RuntimeError, match="pipeline failed after work"):
        workflow.run(sample_raw_items())

    assert workflow.last_execution is not None
    failed = next(stage for stage in workflow.last_execution.stages if stage.status == WorkflowStageStatus.FAILED)
    assert failed.stage_name == "run_pipeline"
    assert failed.duration_ms >= 15.0


def test_stage_result_can_carry_quality_feedback_and_guard_metadata() -> None:
    result = stage_result(
        "collect_quality_feedback",
        started_at=_now(),
        quality_checks=[{"check_type": "has_cards", "passed": True}],
        feedback_events=[{"feedback_type": "weak_signal", "severity": "warning"}],
        guard_results=[{"guard_id": "guard-1", "passed": True}],
    )
    payload = result.to_dict()

    assert payload["quality_checks"] == [{"check_type": "has_cards", "passed": True}]
    assert payload["feedback_events"] == [{"feedback_type": "weak_signal", "severity": "warning"}]
    assert payload["guard_results"] == [{"guard_id": "guard-1", "passed": True}]


class _FailingWorkflow(AINewsWorkflow):
    def run_pipeline(self, selected_signals, *, context):
        raise RuntimeError("pipeline failed")


class _SlowFailingWorkflow(AINewsWorkflow):
    def run_pipeline(self, selected_signals, *, context):
        import time

        time.sleep(0.02)
        raise RuntimeError("pipeline failed after work")


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)
