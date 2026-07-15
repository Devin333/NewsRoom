from __future__ import annotations

from datetime import UTC, datetime

import pytest

from framework.specs import StepSpec, WorkflowSpec
from framework.workflow.checkpoint.durable import (
    DurableWorkflowCheckpoint,
    WorkflowCheckpointRecoveryCursor,
    durable_envelope_from_checkpoint,
)
from framework.workflow.checkpoint.envelope import envelope_from_checkpoint
from framework.workflow.checkpoint.model import WorkflowCheckpoint
from framework.workflow.checkpoint.resume import (
    ResumeMode,
    WorkflowResumePlanner,
    WorkflowResumeRequest,
)
from framework.workflow.runtime.result import StepOutcome


def test_resume_from_step_applies_valid_patch_and_truncates_step_results() -> None:
    workflow = WorkflowSpec(
        workflow_id="wf-resume-plan",
        name="Resume Plan",
        version="1",
        steps=[
            StepSpec("s1", write_keys=["a"]),
            StepSpec("s2", read_keys=["a", "review_route"], write_keys=["b"]),
            StepSpec("s3", read_keys=["b"], write_keys=["c"]),
        ],
    )
    checkpoint = WorkflowCheckpoint(
        checkpoint_id="cp-1",
        run_id="run-1",
        workflow_id=workflow.workflow_id,
        workflow_version=workflow.version,
        current_step_ids=[],
        data_buffer_snapshot={"request": {}, "a": 1, "b": 2, "c": 3},
        step_results={
            "s1": StepOutcome.success("s1", {"a": 1}).to_dict(),
            "s2": StepOutcome.success("s2", {"b": 2}).to_dict(),
            "s3": StepOutcome.success("s3", {"c": 3}).to_dict(),
        },
        path=["s1", "s2", "s3"],
    )

    plan = WorkflowResumePlanner().plan(
        workflow,
        WorkflowResumeRequest(
            mode=ResumeMode.FROM_STEP,
            checkpoint=envelope_from_checkpoint(checkpoint),
            run_id="run-1-resume",
            target_step_id="s2",
            patch={"review_route": {"route": "rewrite"}},
            metadata={"allowed_patch_keys": ["review_route"]},
        ),
    )

    assert plan.run_id == "run-1-resume"
    assert plan.current_step_ids == ["s2"]
    assert plan.initial_path == ["s1"]
    assert sorted(plan.initial_step_results) == ["s1"]
    assert plan.initial_buffer_values["review_route"] == {"route": "rewrite"}
    assert plan.resume_metadata["resume_mode"] == "resume_from_step"
    assert plan.resume_metadata["resume_target_step_id"] == "s2"
    assert plan.resume_metadata["resume_patch_keys"] == ["review_route"]


def test_durable_resume_plan_preserves_verified_exclusive_sequence_cursor() -> None:
    workflow = WorkflowSpec(
        workflow_id="wf-durable-resume-plan",
        name="Durable Resume Plan",
        version="2",
        steps=[StepSpec("s1", write_keys=["value"])],
    )
    checkpoint = DurableWorkflowCheckpoint(
        checkpoint_id="cp-000003-s1",
        run_id="run-durable-resume",
        workflow_id=workflow.workflow_id,
        workflow_version=workflow.version,
        current_step_ids=["s1"],
        data_buffer_snapshot={"request": {}, "value": "accepted"},
        stream_id="run:run-durable-resume",
        last_durable_stream_sequence=3,
        last_event_id="event-3",
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
    )
    envelope = durable_envelope_from_checkpoint(checkpoint)
    cursor = WorkflowCheckpointRecoveryCursor(
        stream_id=checkpoint.stream_id,
        after_sequence=checkpoint.last_durable_stream_sequence,
        last_event_id=checkpoint.last_event_id,
        boundary_verified=True,
    )

    plan = WorkflowResumePlanner().plan(
        workflow,
        WorkflowResumeRequest(
            mode=ResumeMode.EXACT,
            checkpoint=envelope,
            recovery_cursor=cursor,
            run_id="run-durable-resume-next",
        ),
    )

    assert plan.recovery_cursor == cursor
    assert not cursor.should_apply(3)
    assert cursor.should_apply(4)
    assert plan.resume_metadata["checkpoint_stream_id"] == checkpoint.stream_id
    assert plan.resume_metadata["checkpoint_after_sequence"] == 3
    assert plan.resume_metadata["checkpoint_last_event_id"] == "event-3"
    assert plan.resume_metadata["checkpoint_boundary_verified"] is True


def test_durable_resume_request_rejects_unverified_boundary() -> None:
    checkpoint = DurableWorkflowCheckpoint(
        checkpoint_id="cp-unverified",
        run_id="run-unverified",
        workflow_id="wf-unverified",
        workflow_version="2",
        current_step_ids=[],
        data_buffer_snapshot={},
        stream_id="run:run-unverified",
        last_durable_stream_sequence=1,
        last_event_id="event-1",
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="verified recovery cursor"):
        WorkflowResumeRequest(
            mode=ResumeMode.EXACT,
            checkpoint=durable_envelope_from_checkpoint(checkpoint),
        )
