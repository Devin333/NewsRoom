from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from core.framework.artifacts import ArtifactManager
from core.framework.specs import StepSpec, WorkflowSpec
from core.framework.workflow import FunctionStepRegistry, FunctionStepRunner, WorkflowExecutor
from core.framework.workflow.checkpointing import (
    ResumeMode,
    WorkflowResumePlanner,
    WorkflowResumeRequest,
    attach_checkpoint_checksum,
    check_checkpoint_compatibility,
    envelope_from_checkpoint,
)
from core.framework.workflow.step_runner import StepExecutionError
from storage.checkpoint import WorkflowCheckpoint


def test_resume_rejects_mismatched_workflow_id() -> None:
    envelope = envelope_from_checkpoint(
        replace(_checkpoint(), workflow_id="other-workflow")
    )

    result = check_checkpoint_compatibility(envelope=envelope, workflow=_workflow())

    assert result.compatible is False
    assert any("workflow_id" in error for error in result.errors)


def test_resume_rejects_mismatched_workflow_version_by_default() -> None:
    envelope = envelope_from_checkpoint(
        replace(_checkpoint(), workflow_version="2.0")
    )

    result = check_checkpoint_compatibility(envelope=envelope, workflow=_workflow())

    assert result.compatible is False
    assert any("workflow_version" in error for error in result.errors)


def test_resume_rejects_unknown_current_step() -> None:
    envelope = envelope_from_checkpoint(
        replace(_checkpoint(), current_step_ids=["missing"])
    )

    result = check_checkpoint_compatibility(envelope=envelope, workflow=_workflow())

    assert result.compatible is False
    assert any("current_step_ids" in error for error in result.errors)


def test_resume_rejects_unsupported_schema_version() -> None:
    envelope = attach_checkpoint_checksum(
        replace(
            envelope_from_checkpoint(_checkpoint()),
            schema_version="workflow-checkpoint/unknown",
        )
    )

    result = check_checkpoint_compatibility(envelope=envelope, workflow=_workflow())

    assert result.compatible is False
    assert any("schema_version" in error for error in result.errors)


def test_resume_reports_warning_for_extra_step_result_when_not_strict() -> None:
    envelope = envelope_from_checkpoint(
        replace(
            _checkpoint(),
            step_results={
                "plan": {"status": "succeeded", "outputs": {"plan": "outline"}},
                "retired": {"status": "succeeded"},
            },
        )
    )

    result = check_checkpoint_compatibility(
        envelope=envelope,
        workflow=_workflow(),
        strict=False,
    )

    assert result.compatible is True
    assert result.errors == []
    assert any("step_results" in warning for warning in result.warnings)


def test_resume_exact_request_rejects_patch() -> None:
    with pytest.raises(ValueError, match="resume_exact"):
        WorkflowResumeRequest(
            mode=ResumeMode.EXACT,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            patch={"human_review_decision": {"decision": "approved"}},
        )


def test_resume_from_step_request_requires_target_step_id() -> None:
    with pytest.raises(ValueError, match="target_step_id"):
        WorkflowResumeRequest(
            mode=ResumeMode.FROM_STEP,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
        )


def test_resume_after_human_review_request_requires_human_decision() -> None:
    with pytest.raises(ValueError, match="human_decision"):
        WorkflowResumeRequest(
            mode=ResumeMode.AFTER_HUMAN_REVIEW,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
        )


def test_resume_after_approval_request_requires_approval_context() -> None:
    with pytest.raises(ValueError, match="approval_context"):
        WorkflowResumeRequest(
            mode=ResumeMode.AFTER_APPROVAL,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
        )


def test_resume_exact_generates_original_plan() -> None:
    envelope = envelope_from_checkpoint(_checkpoint())

    plan = WorkflowResumePlanner().plan(
        _workflow(),
        WorkflowResumeRequest(
            mode=ResumeMode.EXACT,
            checkpoint=envelope,
            run_id="resume-run",
        ),
    )

    assert plan.mode == ResumeMode.EXACT
    assert plan.run_id == "resume-run"
    assert plan.initial_buffer_values == envelope.data_buffer_snapshot
    assert plan.current_step_ids == envelope.current_step_ids
    assert plan.initial_path == envelope.path
    assert set(plan.initial_step_results) == {"plan"}
    assert plan.resumed_from_checkpoint_id == envelope.checkpoint_id


def test_resume_from_step_truncates_path_and_step_results() -> None:
    envelope = envelope_from_checkpoint(
        replace(
            _checkpoint(),
            current_step_ids=[],
            step_results={
                "plan": {"status": "succeeded", "outputs": {"plan": "outline"}},
                "write": {"status": "succeeded", "outputs": {"report": "draft"}},
            },
            path=["plan", "write"],
        )
    )

    plan = WorkflowResumePlanner().plan(
        _workflow(),
        WorkflowResumeRequest(
            mode=ResumeMode.FROM_STEP,
            checkpoint=envelope,
            target_step_id="write",
        ),
    )

    assert plan.current_step_ids == ["write"]
    assert plan.initial_path == ["plan"]
    assert set(plan.initial_step_results) == {"plan"}


def test_executor_resume_rejects_mismatched_workflow_id(tmp_path) -> None:
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(FunctionStepRegistry()),
        artifact_manager=ArtifactManager(tmp_path),
    )

    with pytest.raises(StepExecutionError, match="workflow_id"):
        executor.resume_from_checkpoint(
            _workflow(),
            replace(_checkpoint(), workflow_id="other"),
            profile="test",
        )


def test_executor_resume_rejects_mismatched_workflow_version(tmp_path) -> None:
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(FunctionStepRegistry()),
        artifact_manager=ArtifactManager(tmp_path),
    )

    with pytest.raises(StepExecutionError, match="workflow_version"):
        executor.resume_from_checkpoint(
            _workflow(),
            replace(_checkpoint(), workflow_version="2.0"),
            profile="test",
        )


def _workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="daily",
        name="Daily",
        version="1.0",
        start_step_id="write",
        steps=[
            StepSpec(
                step_id="plan",
                implementation="sample.plan",
                read_keys=["request"],
                write_keys=["plan"],
            ),
            StepSpec(
                step_id="write",
                implementation="sample.write",
                read_keys=["plan"],
                write_keys=["report"],
            ),
        ],
        metadata={"initial_keys": ["plan"]},
    )


def _checkpoint() -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        checkpoint_id="cp-1",
        run_id="run-1",
        workflow_id="daily",
        workflow_version="1.0",
        current_step_ids=["write"],
        data_buffer_snapshot={"request": {"topic": "ai"}, "plan": "outline"},
        step_results={"plan": {"status": "succeeded", "outputs": {"plan": "outline"}}},
        path=["plan"],
        event_offset=7,
        created_at=datetime(2026, 5, 16, 1, 2, 3, tzinfo=UTC),
        metadata={"profile": "test"},
    )
