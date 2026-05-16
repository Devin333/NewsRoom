from __future__ import annotations

import json

from core.framework.artifacts.filesystem import ArtifactManager
from core.framework.specs import EdgeCondition, EdgeSpec, StepSpec, WorkflowSpec, WorkflowStatus
from core.framework.workflow.executor import WorkflowExecutor
from core.framework.workflow.operations import (
    LocalWorkflowRunOperationService,
    OperationActor,
    WorkflowOperationStatus,
)
from core.framework.workflow.step_runner import FunctionStepRegistry, FunctionStepRunner


def test_running_run_cancel_writes_marker_and_manifest(tmp_path) -> None:
    _write_run_manifest(tmp_path, "run-1", status="running")
    service = LocalWorkflowRunOperationService(artifact_root=tmp_path)

    result = service.cancel_run(
        "run-1",
        "manual cancel",
        actor=OperationActor(actor_id="devin"),
    )

    cancel_payload = json.loads((tmp_path / "run-1" / "cancel.json").read_text())
    manifest = _manifest(tmp_path, "run-1")
    assert result.status == WorkflowOperationStatus.APPLIED
    assert cancel_payload["run_id"] == "run-1"
    assert cancel_payload["operation_id"] == result.operation_id
    assert cancel_payload["reason"] == "manual cancel"
    assert cancel_payload["actor_id"] == "devin"
    assert manifest["status"] == "cancelled"
    assert manifest["cancel_reason"] == "manual cancel"
    assert manifest["cancel_operation_id"] == result.operation_id
    assert manifest["operations"][0]["operation_type"] == "cancel_run"


def test_already_cancelled_run_cancel_is_rejected(tmp_path) -> None:
    _write_run_manifest(tmp_path, "run-1", status="cancelled")
    service = LocalWorkflowRunOperationService(artifact_root=tmp_path)

    result = service.cancel_run("run-1", "again")

    assert result.status == WorkflowOperationStatus.REJECTED
    assert _manifest(tmp_path, "run-1")["operation_count"] == 1


def test_executor_stops_before_next_step_when_cancel_marker_exists(tmp_path) -> None:
    registry = FunctionStepRegistry()

    def step_a(_buffer):
        ArtifactManager(tmp_path).write_json(
            "cancelled-run",
            "cancel.json",
            {"run_id": "cancelled-run", "operation_id": "op_test"},
        )
        return {"a": "done"}

    registry.register("test.step_a", step_a)
    registry.register(
        "test.step_b",
        lambda _buffer: (_ for _ in ()).throw(AssertionError("step_b should not run")),
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(registry),
        artifact_manager=ArtifactManager(tmp_path),
    )

    result = executor.execute(
        _two_step_workflow(),
        {"topic": "ai"},
        profile="test",
        run_id="cancelled-run",
    )

    events = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "cancelled-run" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert result.status == WorkflowStatus.CANCELLED
    assert "workflow_cancelled" in events
    assert "b" not in result.step_results
    assert result.path == ["a"]


def _two_step_workflow() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="cancel-test",
        name="Cancel Test",
        version="1.0",
        start_step_id="a",
        steps=[
            StepSpec(
                step_id="a",
                implementation="test.step_a",
                read_keys=["request"],
                write_keys=["a"],
            ),
            StepSpec(
                step_id="b",
                implementation="test.step_b",
                read_keys=["a"],
                write_keys=["b"],
            ),
        ],
        edges=[
            EdgeSpec(
                edge_id="a-b",
                source_step_id="a",
                target_step_id="b",
                condition=EdgeCondition.ON_SUCCESS,
            )
        ],
    )


def _write_run_manifest(tmp_path, run_id: str, *, status: str) -> None:
    run_dir = tmp_path / run_id
    run_dir.mkdir()
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
