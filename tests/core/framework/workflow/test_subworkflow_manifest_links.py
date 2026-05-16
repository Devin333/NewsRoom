from __future__ import annotations

import json

from core.framework.artifacts import ArtifactManager
from core.framework.specs import StepSpec, StepStatus, StepType, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    StepRunnerRegistry,
    SubworkflowStepRunner,
    WorkflowExecutor,
)


def test_subworkflow_success_records_child_run_in_parent_manifest(tmp_path) -> None:
    result = _run_parent_with_child(
        tmp_path,
        child_function=lambda buffer: {"echo": "ok"},
        parent_write_keys=["subworkflow_result", "child_runs"],
    )

    manifest = result.manifest
    assert result.status == WorkflowStatus.SUCCEEDED
    assert manifest["child_run_ids"] == ["run-parent.child.child"]
    assert manifest["child_runs"][0]["child_run_id"] == "run-parent.child.child"
    assert manifest["child_runs"][0]["workflow_id"] == "child"


def test_subworkflow_child_manifest_records_parent_link(tmp_path) -> None:
    _run_parent_with_child(
        tmp_path,
        child_function=lambda buffer: {"echo": "ok"},
        parent_write_keys=["subworkflow_result", "child_runs"],
    )

    child_manifest = json.loads(
        (tmp_path / "run-parent.child.child" / "manifest.json").read_text(encoding="utf-8")
    )
    assert child_manifest["parent_run_id"] == "run-parent"
    assert child_manifest["parent_step_id"] == "child"


def test_subworkflow_result_includes_event_summary(tmp_path) -> None:
    result = _run_parent_with_child(
        tmp_path,
        child_function=lambda buffer: {"echo": "ok"},
        parent_write_keys=["subworkflow_result", "subworkflow_event_summary"],
    )

    summary = result.output["subworkflow_event_summary"]
    assert summary["status"] == "succeeded"
    assert summary["path"] == ["echo"]
    assert summary["event_count"] >= 1


def test_subworkflow_cancellation_policy_is_recorded(tmp_path) -> None:
    result = _run_parent_with_child(
        tmp_path,
        child_function=lambda buffer: {"echo": "ok"},
        parent_write_keys=["subworkflow_result", "subworkflow_cancellation_policy"],
        step_metadata={"cancellation_policy": {"cascade": True, "mode": "parent_child"}},
    )

    assert result.output["subworkflow_cancellation_policy"] == {
        "cascade": True,
        "mode": "parent_child",
    }
    assert result.step_results["child"].metrics["cancellation_policy"]["cascade"] is True


def test_subworkflow_fail_parent_policy_fails_parent_step(tmp_path) -> None:
    result = _run_parent_with_child(
        tmp_path,
        child_function=lambda buffer: (_ for _ in ()).throw(RuntimeError("child failed")),
        parent_write_keys=["subworkflow_result"],
        step_metadata={"failure_propagation": "fail_parent"},
    )

    assert result.status == WorkflowStatus.FAILED
    assert result.step_results["child"].status == StepStatus.FAILED
    assert result.step_results["child"].error_type == "RuntimeError"


def test_subworkflow_best_effort_policy_succeeds_with_child_failure_recorded(tmp_path) -> None:
    result = _run_parent_with_child(
        tmp_path,
        child_function=lambda buffer: (_ for _ in ()).throw(RuntimeError("child failed")),
        parent_write_keys=["subworkflow_result", "partial_success", "child_failure"],
        step_metadata={"failure_propagation": "best_effort"},
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["partial_success"] is True
    assert result.output["child_failure"]["error_type"] == "RuntimeError"
    assert result.step_results["child"].next_hint == "best_effort"


def test_subworkflow_fallback_output_policy_uses_fallback_output(tmp_path) -> None:
    result = _run_parent_with_child(
        tmp_path,
        child_function=lambda buffer: (_ for _ in ()).throw(RuntimeError("child failed")),
        parent_write_keys=["subworkflow_result", "fallback_value"],
        step_metadata={
            "failure_propagation": "fallback_output",
            "fallback_output": {"fallback_value": "used"},
        },
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.output["fallback_value"] == "used"
    assert result.step_results["child"].next_hint == "fallback_output"


def test_subworkflow_block_parent_policy_returns_blocked(tmp_path) -> None:
    result = _run_parent_with_child(
        tmp_path,
        child_function=lambda buffer: (_ for _ in ()).throw(RuntimeError("child failed")),
        parent_write_keys=["subworkflow_result"],
        step_metadata={"failure_propagation": "block_parent"},
    )

    assert result.status == WorkflowStatus.BLOCKED
    assert result.step_results["child"].status == StepStatus.BLOCKED


def test_subworkflow_inherits_global_budget_tracker(tmp_path) -> None:
    class Tracker:
        def snapshot(self):
            return {"llm_calls": 7}

    result = _run_parent_with_child(
        tmp_path,
        child_function=lambda buffer: {"echo": "ok"},
        parent_write_keys=["subworkflow_result"],
        step_metadata={"inherit_budget": True, "budget_scope": "shared"},
        global_budget_tracker=Tracker(),
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.step_results["child"].metrics["inherit_budget"] is True
    assert result.step_results["child"].metrics["budget_scope"] == "shared"
    assert result.output["subworkflow_result"]["manifest"]["metrics"]["global_budget_usage"] == {
        "llm_calls": 7
    }


def _run_parent_with_child(
    tmp_path,
    *,
    child_function,
    parent_write_keys: list[str],
    step_metadata: dict | None = None,
    global_budget_tracker=None,
):
    functions = FunctionStepRegistry()
    functions.register("child.fn", child_function)
    registry = StepRunnerRegistry.with_function_runner(FunctionStepRunner(functions))
    child = WorkflowSpec(
        workflow_id="child",
        name="Child",
        version="1.0",
        start_step_id="echo",
        steps=[StepSpec("echo", "child.fn", write_keys=["echo"])],
    )
    registry.register(StepType.SUBWORKFLOW, SubworkflowStepRunner({"child": child}, registry))
    metadata = {"workflow_id": "child", **dict(step_metadata or {})}
    parent = WorkflowSpec(
        workflow_id="parent",
        name="Parent",
        version="1.0",
        start_step_id="child",
        steps=[
            StepSpec(
                "child",
                "child",
                step_type=StepType.SUBWORKFLOW,
                write_keys=parent_write_keys,
                metadata=metadata,
            )
        ],
    )
    return WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
        global_budget_tracker=global_budget_tracker,
    ).execute(parent, {}, profile="test", run_id="run-parent")
