from __future__ import annotations

import json
from datetime import UTC, datetime

from core.framework.artifacts.filesystem import ArtifactManager
from core.framework.specs import EdgeCondition, EdgeSpec, StepSpec, WorkflowSpec
from core.framework.workflow.executor import WorkflowExecutor
from core.framework.workflow.operations import (
    LocalWorkflowRunOperationService,
    OperationActor,
    WorkflowOperationStatus,
)
from core.framework.workflow.step_runner import FunctionStepRegistry, FunctionStepRunner
from storage.checkpoint import LocalJsonCheckpointStore, WorkflowCheckpoint


def test_failed_run_can_rerun_from_step(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    checkpoint_store.save_checkpoint(_checkpoint())
    _write_run_manifest(tmp_path, "run-1", status="failed")
    service = _operation_service(tmp_path, checkpoint_store)

    result = service.rerun_from_step(
        "run-1",
        "write",
        actor=OperationActor(actor_id="operator"),
    )

    manifest = _manifest(tmp_path, "run-1")
    new_manifest = _manifest(tmp_path, result.new_run_id or "")
    assert result.status == WorkflowOperationStatus.APPLIED
    assert result.new_run_id
    assert result.new_run_id != "run-1"
    assert manifest["operations"][0]["operation_type"] == "rerun_from_step"
    assert new_manifest["rerun_from_run_id"] == "run-1"
    assert new_manifest["rerun_from_step_id"] == "write"


def test_succeeded_run_can_rerun_from_step_with_new_run_id(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    checkpoint_store.save_checkpoint(_checkpoint())
    _write_run_manifest(tmp_path, "run-1", status="succeeded")

    result = _operation_service(tmp_path, checkpoint_store).rerun_from_step(
        "run-1",
        "write",
    )

    assert result.status == WorkflowOperationStatus.APPLIED
    assert result.new_run_id
    assert result.new_run_id.startswith("run-1-rerun-op_")


def test_rerun_from_step_rejects_missing_target_step(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    checkpoint_store.save_checkpoint(_checkpoint())
    _write_run_manifest(tmp_path, "run-1", status="failed")

    result = _operation_service(tmp_path, checkpoint_store).rerun_from_step(
        "run-1",
        "missing",
    )

    assert result.status == WorkflowOperationStatus.REJECTED
    assert result.new_run_id is None
    assert _manifest(tmp_path, "run-1")["operations"][0]["status"] == "rejected"


def test_rerun_from_step_new_path_continues_from_target(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    checkpoint_store.save_checkpoint(_checkpoint())
    _write_run_manifest(tmp_path, "run-1", status="failed")

    result = _operation_service(tmp_path, checkpoint_store).rerun_from_step(
        "run-1",
        "write",
    )

    new_manifest = _manifest(tmp_path, result.new_run_id or "")
    assert new_manifest["path"] == ["plan", "write"]
    assert set(new_manifest["steps"]) == {"plan", "write"}


def _operation_service(tmp_path, checkpoint_store: LocalJsonCheckpointStore):
    executor = _executor(tmp_path)
    return LocalWorkflowRunOperationService(
        artifact_root=tmp_path,
        workflow=_workflow(),
        runner=_PlanRunner(executor),
        checkpoint_store=checkpoint_store,
    )


def _executor(tmp_path) -> WorkflowExecutor:
    functions = FunctionStepRegistry()
    functions.register("test.plan", lambda buffer: {"plan": f"plan:{buffer.read('request')['topic']}"})
    functions.register("test.write", lambda buffer: {"report": f"report:{buffer.read('plan')}"})
    return WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
        checkpoint_store=LocalJsonCheckpointStore(tmp_path / "checkpoints"),
    )


class _PlanRunner:
    def __init__(self, executor: WorkflowExecutor) -> None:
        self.executor = executor

    def execute_resume_plan(self, workflow: WorkflowSpec, plan, *, profile: str):
        return self.executor.execute(
            workflow,
            plan.initial_buffer_values.get("request") or {},
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
        start_step_id="plan",
        steps=[
            StepSpec(
                step_id="plan",
                implementation="test.plan",
                read_keys=["request"],
                write_keys=["plan"],
            ),
            StepSpec(
                step_id="write",
                implementation="test.write",
                read_keys=["plan"],
                write_keys=["report"],
            ),
        ],
        edges=[
            EdgeSpec(
                edge_id="plan-write",
                source_step_id="plan",
                target_step_id="write",
                condition=EdgeCondition.ON_SUCCESS,
            )
        ],
        metadata={"initial_keys": ["plan"]},
    )


def _checkpoint() -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        checkpoint_id="cp-1",
        run_id="run-1",
        workflow_id="daily",
        workflow_version="1.0",
        current_step_ids=[],
        data_buffer_snapshot={"request": {"topic": "ai"}, "plan": "outline"},
        step_results={
            "plan": {"status": "succeeded", "outputs": {"plan": "outline"}},
            "write": {"status": "failed", "error_message": "boom"},
        },
        path=["plan", "write"],
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


def _manifest(tmp_path, run_id: str) -> dict:
    return json.loads((tmp_path / run_id / "manifest.json").read_text(encoding="utf-8"))
