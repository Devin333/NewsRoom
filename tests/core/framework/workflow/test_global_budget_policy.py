from __future__ import annotations

import json

import pytest

from core.framework.artifacts import ArtifactManager
from core.framework.llm import GlobalBudgetPolicy, GlobalBudgetTracker
from core.framework.specs import StepSpec, StepStatus, StepType, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    StepOutcome,
    StepRunnerRegistry,
    WorkflowExecutor,
    WorkflowBudgetPolicy,
    WorkflowBudgetTracker,
    budget_summary_from_tracker,
)


def test_workflow_budget_policy_rejects_negative_fields() -> None:
    with pytest.raises(ValueError, match="max_tool_calls"):
        WorkflowBudgetPolicy(max_tool_calls=-1)


def test_workflow_budget_policy_serializes_none_limits() -> None:
    policy = WorkflowBudgetPolicy()

    assert policy.to_dict() == {
        "max_total_tokens": None,
        "max_total_cost_usd": None,
        "max_llm_calls": None,
        "max_tool_calls": None,
        "max_wall_time_seconds": None,
    }


def test_workflow_budget_tracker_accumulates_llm_usage() -> None:
    tracker = WorkflowBudgetTracker(WorkflowBudgetPolicy(max_total_tokens=10))

    check = tracker.record_llm_usage(input_tokens=3, output_tokens=4)

    assert check.usage.total_tokens == 7
    assert check.usage.llm_calls == 1
    assert check.exceeded is False


def test_workflow_budget_tracker_accumulates_tool_calls() -> None:
    tracker = WorkflowBudgetTracker(WorkflowBudgetPolicy(max_tool_calls=2))

    tracker.record_tool_call()
    check = tracker.record_tool_call()

    assert check.usage.tool_calls == 2
    assert check.exceeded is False


def test_workflow_budget_tracker_reports_total_token_exceeded() -> None:
    tracker = WorkflowBudgetTracker(WorkflowBudgetPolicy(max_total_tokens=3))

    check = tracker.record_llm_usage(input_tokens=2, output_tokens=2)

    assert check.exceeded is True
    assert check.exceeded_reason == "max_total_tokens"


def test_workflow_budget_tracker_reports_llm_call_exceeded() -> None:
    tracker = WorkflowBudgetTracker(WorkflowBudgetPolicy(max_llm_calls=1))

    tracker.record_llm_usage(input_tokens=1)
    check = tracker.record_llm_usage(input_tokens=1)

    assert check.exceeded is True
    assert check.exceeded_reason == "max_llm_calls"


def test_budget_summary_from_existing_global_tracker() -> None:
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=3))
    tracker.record_llm_call(_usage(2, 3), estimated_cost_usd=0.02)

    summary = budget_summary_from_tracker(tracker)

    assert summary["total_tokens"] == 5
    assert summary["total_cost_usd"] == 0.02
    assert summary["llm_calls"] == 1
    assert summary["exceeded"] is False


def test_budget_summary_reports_exceeded_existing_tracker() -> None:
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_total_tokens=3, on_budget_exceeded="warn"))
    tracker.record_llm_call(_usage(2, 3), estimated_cost_usd=0.02)

    summary = budget_summary_from_tracker(tracker)

    assert summary["exceeded"] is True
    assert summary["exceeded_reason"] == "max_total_tokens"


def test_success_run_writes_budget_summary_to_manifest(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("sample.ok", lambda buffer: {"ok": True})
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=3))
    tracker.record_llm_call(_usage(1, 2), estimated_cost_usd=0.001)
    spec = WorkflowSpec(
        workflow_id="budget-summary",
        name="Budget Summary",
        version="1.0",
        start_step_id="ok",
        steps=[
            StepSpec(
                step_id="ok",
                implementation="sample.ok",
                write_keys=["ok"],
            )
        ],
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
        global_budget_tracker=tracker,
    )

    result = executor.execute(spec, {}, profile="test", run_id="run-budget-summary")

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.manifest["metrics"]["budget"]["llm_calls"] == 1
    assert result.manifest["metrics"]["budget"]["total_tokens"] == 3
    assert result.manifest["metrics"]["budget"]["exceeded"] is False


def test_budget_exceeded_run_writes_budget_summary_to_manifest(tmp_path) -> None:
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
    tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_total_tokens=1, on_budget_exceeded="warn"))
    tracker.record_llm_call(_usage(2, 0), estimated_cost_usd=0.0)
    spec = WorkflowSpec(
        workflow_id="budget-exceeded-summary",
        name="Budget Exceeded Summary",
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

    result = executor.execute(spec, {}, profile="test", run_id="run-budget-exceeded-summary")
    manifest = json.loads(
        (tmp_path / "run-budget-exceeded-summary" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert result.status == WorkflowStatus.BUDGET_EXCEEDED
    assert manifest["metrics"]["budget"]["exceeded"] is True
    assert manifest["metrics"]["budget"]["exceeded_reason"] == "max_total_tokens"


def _usage(input_tokens: int, output_tokens: int):
    from core.framework.llm import TokenUsage

    return TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)
