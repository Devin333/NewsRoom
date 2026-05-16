from __future__ import annotations

from core.framework.artifacts import ArtifactManager
from core.framework.llm import GlobalBudgetPolicy, GlobalBudgetTracker, TokenUsage
from core.framework.specs import (
    ResourcePolicySpec,
    StepSpec,
    StepStatus,
    StepType,
    WorkflowSpec,
)
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    StepOutcome,
    StepRunnerRegistry,
    WorkflowExecutor,
    inspect_workflow_run_diagnostics,
)


def test_resource_policy_block_diagnostics_include_violation_and_action(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("sample.count", lambda buffer: {"count": len(buffer.read("request")["items"])})
    spec = WorkflowSpec(
        workflow_id="resource-diagnostics",
        name="Resource Diagnostics",
        version="1.0",
        start_step_id="count",
        steps=[
            StepSpec(
                step_id="count",
                implementation="sample.count",
                read_keys=["request"],
                write_keys=["count"],
                resource_policy=ResourcePolicySpec(max_items=1),
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
    )

    executor.execute(
        spec,
        {"items": ["a", "b"]},
        profile="test",
        run_id="run-resource-diagnostics",
    )

    diagnostics = inspect_workflow_run_diagnostics(tmp_path / "run-resource-diagnostics")
    health = diagnostics.health_report

    assert any("resource.max_items" in warning for warning in health.warnings)
    assert any("max_items" in action for action in health.suggested_actions)


def test_budget_exceeded_diagnostics_include_reason_and_action(tmp_path) -> None:
    class BudgetRunner:
        def run(self, step, buffer):
            _ = step, buffer
            return StepOutcome(
                status=StepStatus.FAILED,
                outputs={"budget_exceeded": True},
                error_type="WorkflowBudgetExceeded",
                error_message="global budget exceeded",
                error_details={"budget_exceeded": True},
            )

    registry = StepRunnerRegistry()
    registry.register(StepType.FUNCTION, BudgetRunner())
    tracker = GlobalBudgetTracker(
        GlobalBudgetPolicy(max_total_tokens=1, on_budget_exceeded="warn")
    )
    tracker.record_llm_call(TokenUsage(input_tokens=2), estimated_cost_usd=0.0)
    spec = WorkflowSpec(
        workflow_id="budget-diagnostics",
        name="Budget Diagnostics",
        version="1.0",
        start_step_id="budget",
        steps=[StepSpec("budget", "budget.fail")],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
        global_budget_tracker=tracker,
    )

    executor.execute(spec, {}, profile="test", run_id="run-budget-diagnostics")

    diagnostics = inspect_workflow_run_diagnostics(tmp_path / "run-budget-diagnostics")
    health = diagnostics.health_report

    assert any("max_total_tokens" in issue for issue in health.issues)
    assert any("source_limit" in action for action in health.suggested_actions)
