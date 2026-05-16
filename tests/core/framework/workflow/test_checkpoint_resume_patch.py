from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.framework.artifacts import ArtifactManager
from core.framework.specs import EdgeCondition, EdgeSpec, StepSpec, StepType, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    HumanReviewStepRunner,
    StepRunnerRegistry,
    WorkflowExecutor,
)
from core.framework.workflow.checkpointing import (
    ResumeMode,
    WorkflowResumePlanner,
    WorkflowResumeRequest,
    envelope_from_checkpoint,
    validate_resume_patch,
)
from core.framework.workflow.step_runner import StepExecutionError
from storage.checkpoint import WorkflowCheckpoint


def test_resume_with_patch_request_requires_patch() -> None:
    with pytest.raises(ValueError, match="requires patch"):
        WorkflowResumeRequest(
            mode=ResumeMode.WITH_PATCH,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
        )


def test_resume_patch_allows_declared_key() -> None:
    result = validate_resume_patch(
        workflow=_workflow(),
        checkpoint=envelope_from_checkpoint(_checkpoint()),
        patch={"operator_note": "approved"},
        allowed_patch_keys=["operator_note"],
    )

    assert result.valid is True
    assert result.rejected_keys == []


def test_resume_patch_rejects_unknown_key() -> None:
    result = validate_resume_patch(
        workflow=_workflow(),
        checkpoint=envelope_from_checkpoint(_checkpoint()),
        patch={"unknown": "value"},
    )

    assert result.valid is False
    assert result.rejected_keys == ["unknown"]


def test_resume_patch_rejects_request_by_default() -> None:
    result = validate_resume_patch(
        workflow=_workflow(),
        checkpoint=envelope_from_checkpoint(_checkpoint()),
        patch={"request": {"topic": "changed"}},
    )

    assert result.valid is False
    assert result.rejected_keys == ["request"]


def test_resume_patch_allows_current_paused_step_write_key() -> None:
    result = validate_resume_patch(
        workflow=_workflow(),
        checkpoint=envelope_from_checkpoint(_checkpoint()),
        patch={"human_review_request": {"status": "refreshed"}},
    )

    assert result.valid is True


def test_resume_patch_allows_human_review_decision() -> None:
    result = validate_resume_patch(
        workflow=_workflow(),
        checkpoint=envelope_from_checkpoint(_checkpoint()),
        patch={"human_review_decision": {"decision": "approved"}},
    )

    assert result.valid is True


def test_resume_patch_rejects_internal_checkpoint_fields() -> None:
    result = validate_resume_patch(
        workflow=_workflow(),
        checkpoint=envelope_from_checkpoint(_checkpoint()),
        patch={"checksum": "tampered"},
    )

    assert result.valid is False
    assert result.rejected_keys == ["checksum"]


def test_resume_with_patch_merges_patch() -> None:
    envelope = envelope_from_checkpoint(_checkpoint())

    plan = WorkflowResumePlanner().plan(
        _workflow(),
        WorkflowResumeRequest(
            mode=ResumeMode.WITH_PATCH,
            checkpoint=envelope,
            patch={"human_review_decision": {"decision": "approved"}},
        ),
    )

    assert plan.initial_buffer_values["human_review_decision"] == {"decision": "approved"}
    assert plan.current_step_ids == ["review"]


def test_resume_after_human_review_writes_human_decision() -> None:
    plan = WorkflowResumePlanner().plan(
        _workflow(),
        WorkflowResumeRequest(
            mode=ResumeMode.AFTER_HUMAN_REVIEW,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            human_decision={"decision": "approved", "actor_id": "reviewer-1"},
        ),
    )

    assert plan.initial_buffer_values["human_review_decision"] == {
        "decision": "approved",
        "actor_id": "reviewer-1",
        "reason": None,
        "patch": {},
    }
    assert plan.current_step_ids == ["review"]


def test_resume_after_approval_writes_approval_context() -> None:
    approval_context = {
        "approval_id": "appr-1",
        "original_run_id": "run-1",
        "checkpoint_id": "cp-1",
        "actor_id": "approver-1",
        "decision": "approved",
    }

    plan = WorkflowResumePlanner().plan(
        _workflow(),
        WorkflowResumeRequest(
            mode=ResumeMode.AFTER_APPROVAL,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            approval_context=approval_context,
        ),
    )

    assert plan.initial_buffer_values["approval_context"] == approval_context
    assert plan.initial_buffer_values["approval_result"] == approval_context


def test_executor_resume_buffer_updates_use_patch_validation(tmp_path) -> None:
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(FunctionStepRegistry()),
        artifact_manager=ArtifactManager(tmp_path),
    )

    with pytest.raises(StepExecutionError, match="resume patch invalid"):
        executor.resume_from_checkpoint(
            _workflow(),
            _checkpoint(),
            profile="test",
            buffer_updates={"unknown": "value"},
        )


def test_executor_resume_with_human_review_patch_still_works(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register(
        "sample.finalize",
        lambda buffer: {
            "report": (
                f"{buffer.read('request')['topic']}:"
                f"{buffer.read('human_review_decision')['decision']}"
            )
        },
    )
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    registry.register(StepType.HUMAN_REVIEW, HumanReviewStepRunner())
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.resume_from_checkpoint(
        _workflow(),
        _checkpoint(),
        profile="test",
        run_id="resume-with-decision",
        buffer_updates={"human_review_decision": {"decision": "approved"}},
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["report"] == "ai:approved"
    assert result.manifest["resumed_from_checkpoint_id"] == "cp-1"
    assert result.manifest["resume_mode"] == "resume_with_patch"
    assert result.manifest["resume_original_run_id"] == "run-1"
    assert result.manifest["resume_patch_keys"] == ["human_review_decision"]
    assert result.manifest["checkpoint_schema_version"] == "workflow-checkpoint/v1"
    assert result.manifest["checkpoint_checksum"]
    assert result.manifest["resume_metadata"]["partial_artifact_recovery"]["recoverable"] is True


def _workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="daily",
        name="Daily",
        version="1.0",
        start_step_id="review",
        input_schema={"properties": {"human_review_decision": {"type": "object"}}},
        steps=[
            StepSpec(
                step_id="review",
                implementation="human.review",
                step_type=StepType.HUMAN_REVIEW,
                read_keys=["request", "human_review_decision"],
                write_keys=["human_review_request"],
            ),
            StepSpec(
                step_id="finalize",
                implementation="sample.finalize",
                read_keys=["request", "human_review_decision"],
                write_keys=["report"],
                required_output_keys=["report"],
            ),
        ],
        edges=[
            EdgeSpec(
                "review-finalize",
                "review",
                "finalize",
                condition=EdgeCondition.HUMAN_APPROVED,
            )
        ],
        metadata={"initial_keys": ["human_review_decision"]},
    )


def _checkpoint() -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        checkpoint_id="cp-1",
        run_id="run-1",
        workflow_id="daily",
        workflow_version="1.0",
        current_step_ids=["review"],
        data_buffer_snapshot={
            "request": {"topic": "ai"},
            "human_review_request": {"topic": "ai"},
        },
        step_results={
            "review": {
                "status": "paused",
                "outputs": {"human_review_request": {"topic": "ai"}},
            },
        },
        path=["review"],
        event_offset=7,
        created_at=datetime(2026, 5, 16, 1, 2, 3, tzinfo=UTC),
        metadata={"profile": "test"},
    )
