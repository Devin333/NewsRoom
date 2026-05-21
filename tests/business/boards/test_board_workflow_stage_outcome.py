from __future__ import annotations

import pytest

from business.boards._workflow_runtime import WorkflowRecoveryAction, WorkflowStageStatus
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


class _FailingWorkflow(AINewsWorkflow):
    def run_pipeline(self, selected_signals, *, context):
        raise RuntimeError("pipeline failed")
