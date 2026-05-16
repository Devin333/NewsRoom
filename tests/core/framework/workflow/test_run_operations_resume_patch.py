from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

from core.framework.artifacts.filesystem import ArtifactManager
from core.framework.specs import EdgeCondition, EdgeSpec, StepSpec, WorkflowSpec
from core.framework.workflow.executor import WorkflowExecutor
from core.framework.workflow.operations import (
    LocalWorkflowRunOperationService,
    OperationActor,
    WorkflowOperationStatus,
)
from core.framework.workflow.step_runner import (
    FunctionStepRegistry,
    FunctionStepRunner,
    HumanReviewStepRunner,
    StepRunnerRegistry,
)
from storage.checkpoint import LocalJsonCheckpointStore, WorkflowCheckpoint


def test_paused_run_can_resume_with_patch(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    checkpoint_store.save_checkpoint(_checkpoint())
    _write_run_manifest(tmp_path, "run-1", status="waiting_for_human")
    _write_snapshot(tmp_path, "run-1", {"request": {"topic": "ai"}})
    runner = _PlanRunner(_executor_runner(tmp_path))
    service = LocalWorkflowRunOperationService(
        artifact_root=tmp_path,
        workflow=_workflow(),
        runner=runner,
        checkpoint_store=checkpoint_store,
    )

    result = service.resume_with_patch(
        "run-1",
        {"human_review_decision": {"decision": "approved"}},
        actor=OperationActor(actor_id="editor"),
    )

    original_manifest = _manifest(tmp_path, "run-1")
    new_manifest = _manifest(tmp_path, result.new_run_id or "")
    assert result.status == WorkflowOperationStatus.APPLIED
    assert result.new_run_id
    assert new_manifest["resumed_from_checkpoint_id"] == "cp-1"
    assert original_manifest["operations"][0]["operation_type"] == "resume_with_patch"
    assert original_manifest["operations"][0]["details"]["patch_keys"] == [
        "human_review_decision"
    ]
    assert result.details["patch_diff"]["human_review_decision"] == {
        "before": None,
        "after": {"decision": "approved"},
    }


def test_succeeded_run_cannot_resume_with_patch(tmp_path) -> None:
    _write_run_manifest(tmp_path, "run-1", status="succeeded")
    service = LocalWorkflowRunOperationService(artifact_root=tmp_path)

    result = service.resume_with_patch("run-1", {"human_review_decision": {}})

    assert result.status == WorkflowOperationStatus.REJECTED
    assert result.new_run_id is None


def test_resume_patch_invalid_key_is_rejected(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    checkpoint_store.save_checkpoint(_checkpoint())
    _write_run_manifest(tmp_path, "run-1", status="waiting_for_human")
    runner = _PlanRunner(_executor_runner(tmp_path))
    service = LocalWorkflowRunOperationService(
        artifact_root=tmp_path,
        workflow=_workflow(),
        runner=runner,
        checkpoint_store=checkpoint_store,
    )

    result = service.resume_with_patch("run-1", {"request": {"topic": "changed"}})

    assert result.status == WorkflowOperationStatus.FAILED
    assert "resume patch invalid" in result.message


def test_resume_patch_records_patch_diff(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    checkpoint_store.save_checkpoint(
        replace(
            _checkpoint(),
            data_buffer_snapshot={
                "request": {"topic": "ai"},
                "human_review_decision": {"decision": "old"},
            },
        )
    )
    _write_run_manifest(tmp_path, "run-1", status="waiting_for_human")
    _write_snapshot(
        tmp_path,
        "run-1",
        {
            "request": {"topic": "ai"},
            "human_review_decision": {"decision": "old"},
        },
    )
    runner = _PlanRunner(_executor_runner(tmp_path))
    service = LocalWorkflowRunOperationService(
        artifact_root=tmp_path,
        workflow=_workflow(),
        runner=runner,
        checkpoint_store=checkpoint_store,
    )

    result = service.resume_with_patch(
        "run-1",
        {"human_review_decision": {"decision": "approved"}},
    )

    diff = result.details["patch_diff"]["human_review_decision"]
    assert diff["before"] == {"decision": "old"}
    assert diff["after"] == {"decision": "approved"}
    assert _manifest(tmp_path, "run-1")["operations"][0]["details"]["patch_diff"][
        "human_review_decision"
    ] == diff


def _executor_runner(tmp_path) -> WorkflowExecutor:
    functions = FunctionStepRegistry()
    functions.register(
        "test.finalize",
        lambda buffer: {
            "report": (
                f"{buffer.read('request')['topic']}:"
                f"{buffer.read('human_review_decision')['decision']}"
            )
        },
    )
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    registry.register("human_review", HumanReviewStepRunner())
    return WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
        checkpoint_store=LocalJsonCheckpointStore(tmp_path / "checkpoints"),
    )


class _PlanRunner:
    def __init__(self, executor: WorkflowExecutor) -> None:
        self.executor = executor

    def execute_resume_plan(
        self,
        workflow: WorkflowSpec,
        plan,
        *,
        profile: str,
    ):
        request = plan.initial_buffer_values.get("request") or {}
        return self.executor.execute(
            workflow,
            request,
            profile=profile,
            run_id=plan.run_id,
            _initial_buffer_values=plan.initial_buffer_values,
            _current_step_ids=plan.current_step_ids,
            _initial_path=plan.initial_path,
            _initial_step_results=plan.initial_step_results,
            _resumed_checkpoint_id=plan.resumed_from_checkpoint_id,
            _resume_metadata=plan.resume_metadata,
        )


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
                step_type="human_review",
                read_keys=["request", "human_review_decision"],
                write_keys=["human_review_decision"],
                metadata={"decision_key": "human_review_decision"},
            ),
            StepSpec(
                step_id="finalize",
                implementation="test.finalize",
                read_keys=["request", "human_review_decision"],
                write_keys=["report"],
            ),
        ],
        edges=[
            EdgeSpec(
                edge_id="review-finalize",
                source_step_id="review",
                target_step_id="finalize",
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
        data_buffer_snapshot={"request": {"topic": "ai"}},
        step_results={"review": {"status": "paused", "outputs": {}}},
        path=["review"],
        event_offset=7,
        created_at=datetime(2026, 5, 16, 1, 2, 3, tzinfo=UTC),
        metadata={"profile": "test"},
    )


def _write_run_manifest(tmp_path, run_id: str, *, status: str) -> None:
    run_dir = tmp_path / run_id
    run_dir.mkdir(exist_ok=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "workflow_id": "daily",
                "workflow_version": "1.0",
                "profile": "test",
                "status": status,
                "operations": [],
            }
        ),
        encoding="utf-8",
    )


def _write_snapshot(tmp_path, run_id: str, payload: dict) -> None:
    (tmp_path / run_id / "data_buffer_snapshot.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _manifest(tmp_path, run_id: str) -> dict:
    return json.loads((tmp_path / run_id / "manifest.json").read_text(encoding="utf-8"))
