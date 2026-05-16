from __future__ import annotations

import json

from core.framework.artifacts import ArtifactManager
from core.framework.llm import GlobalBudgetPolicy, GlobalBudgetTracker, TokenUsage
from core.framework.specs import ResourcePolicySpec, StepSpec, StepStatus, StepType, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    StepOutcome,
    StepRunnerRegistry,
    WorkflowExecutor,
    WorkflowRootCauseAnalyzer,
    inspect_workflow_run_diagnostics,
)
from storage.checkpoint import LocalJsonCheckpointStore


def test_run_diagnostics_model_exposes_summary_fields(tmp_path) -> None:
    executor = _sample_executor(tmp_path)
    executor.execute(_sample_spec(), {"topic": "ai"}, profile="test", run_id="diag-ok")

    diagnostics = inspect_workflow_run_diagnostics(tmp_path / "diag-ok", strict=True)
    payload = diagnostics.to_dict()

    assert payload["healthy"] is True
    assert payload["severity"] == "ok"
    assert payload["status"] == "succeeded"
    assert payload["resume_available"] is False
    assert payload["metadata"]["resume"]["available"] is False


def test_run_diagnostics_identifies_failed_step_root_cause(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("sample.fail", lambda buffer: (_ for _ in ()).throw(RuntimeError("boom")))
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
    )
    spec = WorkflowSpec(
        workflow_id="diag-failed",
        name="Diag Failed",
        version="1.0",
        start_step_id="fail",
        steps=[StepSpec("fail", "sample.fail")],
    )

    executor.execute(spec, {}, profile="test", run_id="diag-failed-run")
    diagnostics = inspect_workflow_run_diagnostics(tmp_path / "diag-failed-run")

    assert diagnostics.root_cause == "RuntimeError"
    assert diagnostics.failed_step_id == "fail"
    assert any("rerun_from_step" in action for action in diagnostics.suggested_actions)


def test_run_diagnostics_identifies_resource_policy_root_cause(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("sample.count", lambda buffer: {"count": len(buffer.read("request")["items"])})
    spec = WorkflowSpec(
        workflow_id="diag-resource",
        name="Diag Resource",
        version="1.0",
        start_step_id="count",
        steps=[
            StepSpec(
                "count",
                "sample.count",
                read_keys=["request"],
                resource_policy=ResourcePolicySpec(max_items=1),
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
    )

    executor.execute(spec, {"items": [1, 2]}, profile="test", run_id="diag-resource-run")
    diagnostics = inspect_workflow_run_diagnostics(tmp_path / "diag-resource-run")

    assert diagnostics.root_cause == "WorkflowResourcePolicyViolation"
    assert diagnostics.blocked_step_id == "count"
    assert diagnostics.policy_violations == ["resource.max_items:count"]


def test_run_diagnostics_identifies_budget_root_cause(tmp_path) -> None:
    class BudgetRunner:
        def run(self, step, buffer):
            _ = step, buffer
            return StepOutcome(
                status=StepStatus.FAILED,
                error_type="WorkflowBudgetExceeded",
                error_message="budget done",
                error_details={"budget_exceeded": True},
            )

    registry = StepRunnerRegistry()
    registry.register(StepType.FUNCTION, BudgetRunner())
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_total_tokens=1, on_budget_exceeded="warn"))
    tracker.record_llm_call(TokenUsage(input_tokens=2), estimated_cost_usd=0)
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
        global_budget_tracker=tracker,
    )
    spec = WorkflowSpec(
        workflow_id="diag-budget",
        name="Diag Budget",
        version="1.0",
        start_step_id="budget",
        steps=[StepSpec("budget", "budget.fail")],
    )

    executor.execute(spec, {}, profile="test", run_id="diag-budget-run")
    diagnostics = inspect_workflow_run_diagnostics(tmp_path / "diag-budget-run")

    assert diagnostics.root_cause == "WorkflowBudgetExceeded"
    assert diagnostics.failed_step_id == "budget"
    assert any("budget" in action for action in diagnostics.suggested_actions)


def test_root_cause_analyzer_identifies_routing_error_phase() -> None:
    result = WorkflowRootCauseAnalyzer().analyze(
        {},
        [
            {
                "event_type": "routing_error",
                "payload": {"phase": "routing", "step_id": "route", "message": "bad edge"},
            }
        ],
        {},
    )

    assert result.root_cause == "RoutingError"
    assert result.phase == "routing"


def test_paused_run_reports_resume_availability(tmp_path) -> None:
    registry = StepRunnerRegistry()
    registry.register("function", _PauseRunner())
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
        checkpoint_store=LocalJsonCheckpointStore(tmp_path / "checkpoints"),
    )
    executor.execute(_pause_spec(), {}, profile="test", run_id="diag-paused-run")

    diagnostics = inspect_workflow_run_diagnostics(tmp_path / "diag-paused-run")

    assert diagnostics.status == WorkflowStatus.PAUSED.value
    assert diagnostics.resume_available is True
    assert diagnostics.metadata["resume"]["latest_checkpoint_id"]


def test_succeeded_run_reports_resume_unavailable(tmp_path) -> None:
    executor = _sample_executor(tmp_path)
    executor.execute(_sample_spec(), {"topic": "ai"}, profile="test", run_id="diag-success")

    diagnostics = inspect_workflow_run_diagnostics(tmp_path / "diag-success")

    assert diagnostics.resume_available is False
    assert diagnostics.metadata["resume"]["supported_modes"] == []


def test_missing_checkpoint_disables_paused_resume(tmp_path) -> None:
    registry = StepRunnerRegistry()
    registry.register("function", _PauseRunner())
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
    )
    executor.execute(_pause_spec(), {}, profile="test", run_id="diag-paused-no-cp")
    manifest_path = tmp_path / "diag-paused-no-cp" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["latest_checkpoint_id"] = None
    manifest["checkpoint_count"] = 0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    diagnostics = inspect_workflow_run_diagnostics(tmp_path / "diag-paused-no-cp")

    assert diagnostics.resume_available is False


def _sample_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="diag-sample",
        name="Diag Sample",
        version="1.0",
        start_step_id="ok",
        steps=[StepSpec("ok", "sample.ok", write_keys=["ok"])],
    )


def _sample_executor(tmp_path) -> WorkflowExecutor:
    functions = FunctionStepRegistry()
    functions.register("sample.ok", lambda buffer: {"ok": True})
    return WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
    )


def _pause_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="diag-pause",
        name="Diag Pause",
        version="1.0",
        start_step_id="pause",
        steps=[StepSpec("pause", "pause.now")],
    )


class _PauseRunner:
    def run(self, step, buffer):
        _ = step, buffer
        return StepOutcome(status=StepStatus.PAUSED, next_hint="pause")
