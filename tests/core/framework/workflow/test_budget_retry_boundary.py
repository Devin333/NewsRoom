import json

from core.framework.artifacts import ArtifactManager
from core.framework.specs import (
    FailurePolicySpec,
    RetryPolicySpec,
    StepSpec,
    StepStatus,
    StepType,
    WorkflowSpec,
    WorkflowStatus,
)
from core.framework.workflow import StepOutcome, StepRunnerRegistry, WorkflowExecutor


def test_budget_exceeded_stops_step_retry_and_failure_fallback(tmp_path) -> None:
    calls = {"budget": 0, "fallback": 0}

    class BudgetRunner:
        def run(self, step, buffer):
            if step.step_id == "fallback":
                calls["fallback"] += 1
                buffer.write("recovered", True)
                return StepOutcome(status=StepStatus.SUCCEEDED, outputs={"recovered": True})
            calls["budget"] += 1
            return StepOutcome(
                status=StepStatus.FAILED,
                outputs={"budget_exceeded": True},
                error_type="WorkflowBudgetExceeded",
                error_message="global budget exceeded",
                error_details={"budget_exceeded": True},
            )

    registry = StepRunnerRegistry()
    registry.register(StepType.FUNCTION, BudgetRunner())
    spec = WorkflowSpec(
        workflow_id="budget-boundary",
        name="Budget Boundary",
        version="1.0",
        start_step_id="budget",
        steps=[
            StepSpec(
                "budget",
                "budget.fail",
                retry_policy=RetryPolicySpec(max_retries=2),
                failure_policy=FailurePolicySpec(fallback_step_id="fallback"),
            ),
            StepSpec("fallback", "fallback.recover", write_keys=["recovered"]),
        ],
        edges=[],
    )
    executor = WorkflowExecutor(
        function_step_runner=None,
        step_runner_registry=registry,
        artifact_manager=ArtifactManager(tmp_path),
        global_budget_tracker=_FakeBudgetTracker(),
    )

    result = executor.execute(spec, {}, profile="test", run_id="run-budget-boundary")
    events = [
        json.loads(line)["event_type"]
        for line in (tmp_path / "run-budget-boundary" / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert result.status == WorkflowStatus.BUDGET_EXCEEDED
    assert calls == {"budget": 1, "fallback": 0}
    assert (tmp_path / "run-budget-boundary" / "error.json").exists()
    assert (tmp_path / "run-budget-boundary" / "metrics.json").exists()
    assert "step_failed" in events
    assert "workflow_budget_exceeded" in events
    assert result.manifest["metrics"]["global_budget_usage"] == {"llm_calls": 3}


class _FakeBudgetTracker:
    def snapshot(self):
        return {"llm_calls": 3}
