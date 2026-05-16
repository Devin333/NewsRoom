from __future__ import annotations

import json

from core.framework.artifacts import ArtifactManager
from core.framework.specs import StepSpec, StepType, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    HumanReviewRequest,
    HumanReviewStepRunner,
    StepRunnerRegistry,
    WorkflowExecutor,
)
from storage.checkpoint import LocalJsonCheckpointStore


def test_human_review_request_contains_run_step_workflow_and_checkpoint() -> None:
    request = HumanReviewRequest(
        request_id="human_review:run-1:review:cp-1",
        run_id="run-1",
        step_id="review",
        workflow_id="daily",
        workflow_version="1.0",
        checkpoint_id="cp-1",
        review_type="editorial",
        required_role="editor",
        created_at="2026-05-16T01:02:03Z",
        expires_at=None,
        inputs={"request": {"topic": "ai"}},
        metadata={"approval_id": "appr-1"},
    )

    payload = request.to_dict()

    assert payload["run_id"] == "run-1"
    assert payload["step_id"] == "review"
    assert payload["workflow_id"] == "daily"
    assert payload["checkpoint_id"] == "cp-1"
    assert HumanReviewRequest.from_dict(payload) == request


def test_human_review_runner_generates_stable_request_payload(tmp_path) -> None:
    executor = _executor(tmp_path, checkpoint_store=None)
    result = executor.execute(
        _workflow(),
        {"topic": "ai"},
        profile="test",
        run_id="run-human-pause",
    )

    request = result.output["human_review_request"]

    assert result.status == WorkflowStatus.WAITING_FOR_HUMAN
    assert request["request_id"] == "human_review:run-human-pause:review:latest"
    assert request["run_id"] == "run-human-pause"
    assert request["step_id"] == "review"
    assert request["workflow_id"] == "human-review"
    assert request["workflow_version"] == "1.0"
    assert request["checkpoint_id"] is None
    assert request["review_type"] == "editorial"
    assert request["required_role"] == "editor"
    assert request["metadata"]["approval_id"] == request["request_id"]
    assert request["metadata"]["implementation"] == "human.review"
    assert request["inputs"]["request"]["topic"] == "ai"


def test_human_review_pause_writes_checkpoint_manifest_pause_and_events(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    executor = _executor(tmp_path, checkpoint_store=checkpoint_store)

    result = executor.execute(
        _workflow(),
        {"topic": "ai"},
        profile="test",
        run_id="run-human-checkpoint",
    )

    run_dir = tmp_path / "runs" / "run-human-checkpoint"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    pause = json.loads((run_dir / "pause.json").read_text(encoding="utf-8"))
    event_types = [
        json.loads(line)["event_type"]
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    checkpoint = checkpoint_store.get_latest_checkpoint("run-human-checkpoint")

    assert result.status == WorkflowStatus.WAITING_FOR_HUMAN
    assert checkpoint is not None
    assert manifest["checkpoint_count"] == 1
    assert manifest["latest_checkpoint_id"] == checkpoint.checkpoint_id
    assert pause["latest_checkpoint_id"] == checkpoint.checkpoint_id
    assert event_types.count("human_review_requested") == 1
    assert "workflow_paused" in event_types


def _executor(
    tmp_path,
    *,
    checkpoint_store: LocalJsonCheckpointStore | None,
) -> WorkflowExecutor:
    registry = StepRunnerRegistry()
    registry.register(StepType.HUMAN_REVIEW, HumanReviewStepRunner())
    return WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path / "runs"),
        checkpoint_store=checkpoint_store,
    )


def _workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="human-review",
        name="Human Review",
        version="1.0",
        start_step_id="review",
        steps=[
            StepSpec(
                step_id="review",
                implementation="human.review",
                step_type=StepType.HUMAN_REVIEW,
                read_keys=["request", "human_review_decision"],
                write_keys=["human_review_request"],
                required_output_keys=["human_review_request"],
                metadata={
                    "review_type": "editorial",
                    "required_role": "editor",
                    "review_timeout_seconds": 3600,
                },
            )
        ],
        metadata={"initial_keys": ["human_review_decision"]},
    )
