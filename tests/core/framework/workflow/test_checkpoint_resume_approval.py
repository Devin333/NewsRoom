from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.framework.artifacts import ArtifactManager
from core.framework.specs import EdgeCondition, EdgeSpec, StepSpec, StepType, WorkflowSpec
from core.framework.workflow import FunctionStepRegistry, FunctionStepRunner, HumanReviewStepRunner, StepRunnerRegistry, WorkflowExecutor
from core.framework.workflow.checkpointing import (
    ResumeMode,
    WorkflowResumePlanner,
    WorkflowResumeRequest,
    envelope_from_checkpoint,
    validate_approval_resume_binding,
)
from storage.checkpoint import WorkflowCheckpoint


def test_approval_binding_rejects_missing_approval_id() -> None:
    context = _approval_context()
    context.pop("approval_id")

    with pytest.raises(ValueError, match="approval_id"):
        validate_approval_resume_binding(
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            approval_context=context,
        )


def test_approval_binding_rejects_missing_original_run_id() -> None:
    context = _approval_context()
    context.pop("original_run_id")

    with pytest.raises(ValueError, match="original_run_id"):
        validate_approval_resume_binding(
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            approval_context=context,
        )


def test_approval_binding_rejects_mismatched_original_run_id() -> None:
    context = {**_approval_context(), "original_run_id": "other-run"}

    with pytest.raises(ValueError, match="original_run_id"):
        validate_approval_resume_binding(
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            approval_context=context,
        )


def test_approval_binding_rejects_mismatched_checkpoint_id() -> None:
    context = {**_approval_context(), "checkpoint_id": "other-checkpoint"}

    with pytest.raises(ValueError, match="checkpoint_id"):
        validate_approval_resume_binding(
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            approval_context=context,
        )


def test_approved_approval_context_generates_resume_plan() -> None:
    plan = WorkflowResumePlanner().plan(
        _workflow(),
        WorkflowResumeRequest(
            mode=ResumeMode.AFTER_APPROVAL,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            approval_context=_approval_context(),
        ),
    )

    assert plan.initial_buffer_values["approval_context"]["approval_id"] == "appr-1"
    assert plan.initial_buffer_values["human_review_decision"]["decision"] == "approved"
    assert plan.resume_metadata["resume_approval_id"] == "appr-1"
    assert plan.resume_metadata["resume_actor_id"] == "operator"


def test_rejected_approval_context_routes_to_rejected_path() -> None:
    plan = WorkflowResumePlanner().plan(
        _workflow(),
        WorkflowResumeRequest(
            mode=ResumeMode.AFTER_APPROVAL,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            approval_context={**_approval_context(), "decision": "rejected"},
        ),
    )

    assert plan.initial_buffer_values["human_review_decision"]["decision"] == "rejected"
    assert plan.current_step_ids == ["review"]


def test_approval_resume_manifest_records_approval_metadata(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("sample.publish", lambda buffer: {"report": "published"})
    functions.register(
        "sample.blocked",
        lambda buffer: {"blocked_report": buffer.read("human_review_decision")},
    )
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    registry.register(StepType.HUMAN_REVIEW, HumanReviewStepRunner())
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )
    plan = WorkflowResumePlanner().plan(
        _workflow(),
        WorkflowResumeRequest(
            mode=ResumeMode.AFTER_APPROVAL,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            run_id="approval-resume",
            approval_context=_approval_context(),
        ),
    )

    result = executor.execute(
        _workflow(),
        request=plan.initial_buffer_values["request"],
        profile="test",
        run_id=plan.run_id,
        _initial_buffer_values=plan.initial_buffer_values,
        _current_step_ids=plan.current_step_ids,
        _initial_path=plan.initial_path,
        _initial_step_results=plan.initial_step_results,
        _resumed_checkpoint_id=plan.resumed_from_checkpoint_id,
        _resume_metadata=plan.resume_metadata,
    )

    assert result.manifest["resume_mode"] == "resume_after_approval"
    assert result.manifest["resume_approval_id"] == "appr-1"
    assert result.manifest["resume_actor_id"] == "operator"


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
                step_id="publish",
                implementation="sample.publish",
                read_keys=["human_review_decision"],
                write_keys=["report"],
            ),
            StepSpec(
                step_id="blocked",
                implementation="sample.blocked",
                read_keys=["human_review_decision"],
                write_keys=["blocked_report"],
            ),
        ],
        edges=[
            EdgeSpec("review-publish", "review", "publish", condition=EdgeCondition.HUMAN_APPROVED),
            EdgeSpec("review-blocked", "review", "blocked", condition=EdgeCondition.HUMAN_REJECTED),
        ],
        metadata={"initial_keys": ["human_review_decision"]},
    )


def _approval_context() -> dict[str, str]:
    return {
        "approval_id": "appr-1",
        "original_run_id": "run-1",
        "checkpoint_id": "cp-1",
        "approved_by": "operator",
        "decision": "approved",
    }


def _checkpoint() -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        checkpoint_id="cp-1",
        run_id="run-1",
        workflow_id="daily",
        workflow_version="1.0",
        current_step_ids=["review"],
        data_buffer_snapshot={"request": {"topic": "ai"}},
        step_results={"review": {"status": "paused", "outputs": {}}},
        path=["review"],
        event_offset=7,
        created_at=datetime(2026, 5, 16, 1, 2, 3, tzinfo=UTC),
        metadata={"profile": "test"},
    )
