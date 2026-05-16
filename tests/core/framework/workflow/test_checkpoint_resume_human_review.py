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
    HumanReviewResumeDecision,
    ResumeMode,
    WorkflowResumePlanner,
    WorkflowResumeRequest,
    envelope_from_checkpoint,
)
from storage.checkpoint import WorkflowCheckpoint


def test_human_review_resume_without_decision_fails() -> None:
    with pytest.raises(ValueError, match="human_decision"):
        WorkflowResumeRequest(
            mode=ResumeMode.AFTER_HUMAN_REVIEW,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
        )


def test_human_review_resume_rejects_missing_actor_id() -> None:
    with pytest.raises(ValueError, match="actor_id"):
        HumanReviewResumeDecision(decision="approved", actor_id="")


def test_human_review_approved_writes_decision() -> None:
    plan = WorkflowResumePlanner().plan(
        _workflow(),
        WorkflowResumeRequest(
            mode=ResumeMode.AFTER_HUMAN_REVIEW,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            human_decision={"decision": "approved", "actor_id": "editor"},
        ),
    )

    assert plan.initial_buffer_values["human_review_decision"]["decision"] == "approved"
    assert plan.initial_buffer_values["human_review_decision"]["actor_id"] == "editor"
    assert plan.resume_metadata["resume_human_decision"] == "approved"
    assert plan.resume_metadata["resume_actor_id"] == "editor"


def test_human_review_needs_changes_merges_patch() -> None:
    plan = WorkflowResumePlanner().plan(
        _workflow(),
        WorkflowResumeRequest(
            mode=ResumeMode.AFTER_HUMAN_REVIEW,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            human_decision={
                "decision": "needs_changes",
                "actor_id": "editor",
                "patch": {"revision_note": "tighten citations"},
            },
        ),
    )

    assert plan.initial_buffer_values["revision_note"] == "tighten citations"
    assert plan.initial_buffer_values["human_review_decision"]["decision"] == "needs_changes"


def test_human_review_rejected_routes_human_rejected(tmp_path) -> None:
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
            mode=ResumeMode.AFTER_HUMAN_REVIEW,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            run_id="human-rejected-resume",
            human_decision={"decision": "rejected", "actor_id": "editor"},
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

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["blocked_report"]["decision"] == "rejected"
    assert "report" not in result.output
    assert result.manifest["resume_human_decision"] == "rejected"
    assert result.manifest["resume_actor_id"] == "editor"


def _workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="daily",
        name="Daily",
        version="1.0",
        start_step_id="review",
        input_schema={
            "properties": {
                "human_review_decision": {"type": "object"},
                "revision_note": {"type": "string"},
            }
        },
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
        metadata={"initial_keys": ["human_review_decision", "revision_note"]},
    )


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
