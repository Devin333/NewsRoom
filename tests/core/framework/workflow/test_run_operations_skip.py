from __future__ import annotations

import json
from datetime import UTC, datetime

from core.framework.artifacts.filesystem import ArtifactManager
from core.framework.specs import EdgeCondition, EdgeSpec, StepSpec, WorkflowSpec
from core.framework.workflow.executor import WorkflowExecutor
from core.framework.workflow.operations import (
    LocalWorkflowRunOperationService,
    WorkflowOperationStatus,
)
from core.framework.workflow.step_runner import FunctionStepRegistry, FunctionStepRunner
from storage.checkpoint import LocalJsonCheckpointStore, WorkflowCheckpoint


def test_skip_step_rejects_step_without_manual_skip_metadata(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    checkpoint_store.save_checkpoint(_checkpoint())
    _write_run_manifest(tmp_path, "run-1", status="failed")

    result = _service(
        tmp_path,
        checkpoint_store,
        workflow=_workflow(allow_manual_skip=False),
    ).skip_step("run-1", "optional", "not needed")

    assert result.status == WorkflowOperationStatus.REJECTED
    assert "allow manual skip" in result.message


def test_skip_step_allows_declared_manual_skip_and_continues(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    checkpoint_store.save_checkpoint(_checkpoint())
    _write_run_manifest(tmp_path, "run-1", status="failed")

    result = _service(tmp_path, checkpoint_store).skip_step(
        "run-1",
        "optional",
        "not needed",
    )

    original_manifest = _manifest(tmp_path, "run-1")
    new_manifest = _manifest(tmp_path, result.new_run_id or "")
    assert result.status == WorkflowOperationStatus.APPLIED
    assert original_manifest["operations"][0]["operation_type"] == "skip_step"
    assert new_manifest["steps"]["optional"]["status"] == "skipped"
    assert new_manifest["steps"]["finalize"]["outputs"]["report"] == "fallback"
    assert new_manifest["path"] == ["plan", "optional", "finalize"]


def test_skip_step_audit_records_events(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    checkpoint_store.save_checkpoint(_checkpoint())
    _write_run_manifest(tmp_path, "run-1", status="failed")

    _service(tmp_path, checkpoint_store).skip_step("run-1", "optional", "not needed")

    event_types = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "run-1" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert "run_operation_applied" in event_types
    assert "step_skipped" in event_types


def test_skip_step_requires_valid_skip_output(tmp_path) -> None:
    checkpoint_store = LocalJsonCheckpointStore(tmp_path / "checkpoints")
    checkpoint_store.save_checkpoint(_checkpoint())
    _write_run_manifest(tmp_path, "run-1", status="failed")

    result = _service(
        tmp_path,
        checkpoint_store,
        workflow=_workflow(skip_output={}),
    ).skip_step("run-1", "optional", "not needed")

    assert result.status == WorkflowOperationStatus.REJECTED
    assert "missing required output keys" in result.message


def _service(
    tmp_path,
    checkpoint_store: LocalJsonCheckpointStore,
    *,
    workflow: WorkflowSpec | None = None,
):
    executor = _executor(tmp_path)
    return LocalWorkflowRunOperationService(
        artifact_root=tmp_path,
        workflow=workflow or _workflow(),
        runner=_PlanRunner(executor),
        checkpoint_store=checkpoint_store,
    )


def _executor(tmp_path) -> WorkflowExecutor:
    functions = FunctionStepRegistry()
    functions.register("test.plan", lambda buffer: {"plan": f"plan:{buffer.read('request')['topic']}"})
    functions.register("test.optional", lambda _buffer: {"optional_result": "real"})
    functions.register("test.finalize", lambda buffer: {"report": buffer.read("optional_result")})
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


def _workflow(
    *,
    allow_manual_skip: bool = True,
    skip_output: dict | None = None,
) -> WorkflowSpec:
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
                step_id="optional",
                implementation="test.optional",
                read_keys=["plan"],
                write_keys=["optional_result"],
                required_output_keys=["optional_result"],
                nullable_output_keys=["optional_result"],
                metadata={
                    "allow_manual_skip": allow_manual_skip,
                    "skip_output": (
                        {"optional_result": "fallback"}
                        if skip_output is None
                        else skip_output
                    ),
                    "skip_next_hint": "skipped",
                },
            ),
            StepSpec(
                step_id="finalize",
                implementation="test.finalize",
                read_keys=["optional_result"],
                write_keys=["report"],
            ),
        ],
        edges=[
            EdgeSpec(
                edge_id="optional-finalize",
                source_step_id="optional",
                target_step_id="finalize",
                condition=EdgeCondition.ALWAYS,
            )
        ],
        metadata={"initial_keys": ["plan", "optional_result"]},
    )


def _checkpoint() -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        checkpoint_id="cp-1",
        run_id="run-1",
        workflow_id="daily",
        workflow_version="1.0",
        current_step_ids=["optional"],
        data_buffer_snapshot={"request": {"topic": "ai"}, "plan": "outline"},
        step_results={"plan": {"status": "succeeded", "outputs": {"plan": "outline"}}},
        path=["plan"],
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
