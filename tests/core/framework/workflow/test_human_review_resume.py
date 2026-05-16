from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

from core.framework.artifacts import ArtifactManager
from core.framework.specs import StepSpec, StepType, WorkflowSpec
from core.framework.specs import WorkflowStatus
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    HumanReviewStepRunner,
    ResumeMode,
    StepRunnerRegistry,
    WorkflowExecutor,
    WorkflowResumePlanner,
    WorkflowResumeRequest,
    envelope_from_checkpoint,
)
from storage.checkpoint import WorkflowCheckpoint


def test_human_review_resume_requires_approval_or_request_id_when_bound() -> None:
    with pytest.raises(ValueError, match="approval_id or request_id"):
        WorkflowResumePlanner().plan(
            _workflow(),
            WorkflowResumeRequest(
                mode=ResumeMode.AFTER_HUMAN_REVIEW,
                checkpoint=envelope_from_checkpoint(_checkpoint()),
                human_decision={"decision": "approved", "actor_id": "editor"},
            ),
        )


def test_human_review_resume_rejects_mismatched_approval_id() -> None:
    with pytest.raises(ValueError, match="approval_id"):
        WorkflowResumePlanner().plan(
            _workflow(),
            WorkflowResumeRequest(
                mode=ResumeMode.AFTER_HUMAN_REVIEW,
                checkpoint=envelope_from_checkpoint(_checkpoint()),
                human_decision={
                    "decision": "approved",
                    "actor_id": "editor",
                    "approval_id": "wrong",
                    "actor_roles": ["editor"],
                },
            ),
        )


def test_human_review_resume_accepts_matching_request_id() -> None:
    plan = WorkflowResumePlanner().plan(
        _workflow(),
        WorkflowResumeRequest(
            mode=ResumeMode.AFTER_HUMAN_REVIEW,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            human_decision={
                "decision": "approved",
                "actor_id": "editor",
                "request_id": "human_review:run-1:review:latest",
                "actor_roles": ["editor"],
            },
        ),
    )

    assert plan.initial_buffer_values["human_review_decision"]["request_id"] == (
        "human_review:run-1:review:latest"
    )
    assert plan.resume_metadata["resume_human_review_request_id"] == (
        "human_review:run-1:review:latest"
    )


def test_human_review_resume_rejects_expired_request() -> None:
    with pytest.raises(ValueError, match="expired"):
        WorkflowResumePlanner().plan(
            _workflow(),
            WorkflowResumeRequest(
                mode=ResumeMode.AFTER_HUMAN_REVIEW,
                checkpoint=envelope_from_checkpoint(
                    _checkpoint(
                        request_overrides={"expires_at": "2026-05-15T01:02:03Z"}
                    )
                ),
                human_decision={
                    "decision": "approved",
                    "actor_id": "editor",
                    "approval_id": "appr-1",
                    "actor_roles": ["editor"],
                },
            ),
        )


def test_human_review_resume_rejects_actor_without_required_role() -> None:
    with pytest.raises(ValueError, match="required role"):
        WorkflowResumePlanner().plan(
            _workflow(),
            WorkflowResumeRequest(
                mode=ResumeMode.AFTER_HUMAN_REVIEW,
                checkpoint=envelope_from_checkpoint(_checkpoint()),
                human_decision={
                    "decision": "approved",
                    "actor_id": "writer",
                    "approval_id": "appr-1",
                    "actor_roles": ["writer"],
                },
            ),
        )


def test_human_review_resume_writes_decision_audit_and_manifest(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("sample.publish", lambda buffer: {"report": "published"})
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    registry.register(StepType.HUMAN_REVIEW, HumanReviewStepRunner())
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )
    plan = WorkflowResumePlanner().plan(
        _workflow_with_publish(),
        WorkflowResumeRequest(
            mode=ResumeMode.AFTER_HUMAN_REVIEW,
            checkpoint=envelope_from_checkpoint(_checkpoint()),
            run_id="run-human-resumed",
            human_decision={
                "decision": "approved",
                "actor_id": "editor",
                "approval_id": "appr-1",
                "actor_roles": ["editor"],
            },
        ),
    )

    result = executor.execute(
        _workflow_with_publish(),
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
    manifest = json.loads(
        (tmp_path / "run-human-resumed" / "manifest.json").read_text(encoding="utf-8")
    )
    event_types = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "run-human-resumed" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert result.status == WorkflowStatus.SUCCEEDED
    assert manifest["human_reviews"][0]["decision"] == "approved"
    assert manifest["human_reviews"][0]["actor_id"] == "editor"
    assert manifest["human_reviews"][0]["approval_id"] == "appr-1"
    assert "human_review_decision_received" in event_types
    assert "human_review_approved" in event_types


def _workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="daily",
        name="Daily",
        version="1.0",
        start_step_id="review",
        steps=[
            StepSpec(
                step_id="review",
                implementation="human.review",
                step_type=StepType.HUMAN_REVIEW,
                read_keys=["request", "human_review_decision"],
                write_keys=["human_review_request"],
            ),
        ],
        metadata={"initial_keys": ["human_review_decision"]},
    )


def _workflow_with_publish() -> WorkflowSpec:
    workflow = _workflow()
    return WorkflowSpec(
        workflow_id=workflow.workflow_id,
        name=workflow.name,
        version=workflow.version,
        start_step_id=workflow.start_step_id,
        steps=[
            *workflow.steps,
            StepSpec(
                step_id="publish",
                implementation="sample.publish",
                read_keys=["human_review_decision"],
                write_keys=["report"],
            ),
        ],
        edges=[
            {
                "edge_id": "review-publish",
                "source_step_id": "review",
                "target_step_id": "publish",
                "condition": "human_approved",
            }
        ],
        metadata=workflow.metadata,
    )


def _checkpoint(
    *,
    request_overrides: dict | None = None,
) -> WorkflowCheckpoint:
    request = {
        "request_id": "human_review:run-1:review:latest",
        "run_id": "run-1",
        "step_id": "review",
        "workflow_id": "daily",
        "workflow_version": "1.0",
        "checkpoint_id": None,
        "review_type": "editorial",
        "required_role": "editor",
        "created_at": "2026-05-16T01:02:03Z",
        "expires_at": None,
        "inputs": {"request": {"topic": "ai"}},
        "metadata": {"approval_id": "appr-1"},
    }
    request.update(request_overrides or {})
    return WorkflowCheckpoint(
        checkpoint_id="cp-1",
        run_id="run-1",
        workflow_id="daily",
        workflow_version="1.0",
        current_step_ids=["review"],
        data_buffer_snapshot={
            "request": {"topic": "ai"},
            "human_review_request": request,
        },
        step_results={
            "review": {
                "status": "paused",
                "outputs": {"human_review_request": request},
            },
        },
        path=["review"],
        event_offset=7,
        created_at=datetime(2026, 5, 16, 1, 2, 3, tzinfo=UTC),
        metadata={"profile": "test"},
    )
