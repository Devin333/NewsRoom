from __future__ import annotations

from core.framework.artifacts import ArtifactManager
from core.framework.llm import GlobalBudgetPolicy, GlobalBudgetTracker, TokenUsage
from core.framework.specs import EdgeSpec, StepSpec, WorkflowSpec
from core.framework.workflow import (
    FunctionStepRegistry,
    FunctionStepRunner,
    WorkflowExecutor,
    compare_workflow_runs,
)


def test_run_comparison_reports_status_path_output_metrics_and_artifacts(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("sample.a", lambda buffer: {"a": True})
    functions.register("sample.b", lambda buffer: {"b": True})
    functions.register("sample.out", lambda buffer: {"report": "ok"})
    functions.register("sample.out.v2", lambda buffer: {"report": "ok", "summary": "new"})
    base_tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=10))
    base_tracker.record_llm_call(TokenUsage(input_tokens=1), estimated_cost_usd=0.0)
    target_tracker = GlobalBudgetTracker(GlobalBudgetPolicy(max_llm_calls=10))
    target_tracker.record_llm_call(TokenUsage(input_tokens=3), estimated_cost_usd=0.0)

    WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
        global_budget_tracker=base_tracker,
    ).execute(_base_spec(), {}, profile="test", run_id="compare-wfr13-base")
    WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
        global_budget_tracker=target_tracker,
    ).execute(_target_spec(), {}, profile="test", run_id="compare-wfr13-target")

    comparison = compare_workflow_runs(
        tmp_path,
        "compare-wfr13-base",
        "compare-wfr13-target",
        strict=True,
    )
    payload = comparison.to_dict()

    assert payload["status_changed"] is False
    assert payload["path_diff"]["changed"] is True
    assert payload["output_diff"]["added_keys"] == ["b", "summary"]
    assert payload["metric_diff"]["budget"]["changed"] is True
    assert payload["artifact_diff"]["changed"] is False


def _base_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="compare-wfr13",
        name="Compare WFR13",
        version="1.0",
        start_step_id="a",
        steps=[
            StepSpec("a", "sample.a", write_keys=["a"]),
            StepSpec("out", "sample.out", write_keys=["report"]),
        ],
        edges=[EdgeSpec("a-out", "a", "out")],
    )


def _target_spec() -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id="compare-wfr13",
        name="Compare WFR13",
        version="1.0",
        start_step_id="b",
        steps=[
            StepSpec("b", "sample.b", write_keys=["b"]),
            StepSpec("out", "sample.out.v2", write_keys=["report", "summary"]),
        ],
        edges=[EdgeSpec("b-out", "b", "out")],
    )
