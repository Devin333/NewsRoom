from __future__ import annotations

import ast
from pathlib import Path

import pytest

from framework.harness import (
    HarnessBudget,
    HarnessDecision,
    HarnessDecisionType,
    HarnessRetryPolicy,
    HarnessRunSpec,
    HarnessState,
    HarnessStepSpec,
    HarnessValidationError,
    HarnessWorkerType,
)
from framework.harness.workflow.spec import HarnessRoutingRule, HarnessWorkflowSpec


def test_workflow_spec_requires_entry_step() -> None:
    step = HarnessStepSpec(step_id="collect", worker_type=HarnessWorkerType.LLM)

    with pytest.raises(HarnessValidationError):
        HarnessWorkflowSpec(workflow_id="research", steps=(step,), entry_step_id="")


def test_workflow_spec_rejects_duplicate_step_ids() -> None:
    step = HarnessStepSpec(step_id="collect", worker_type="llm")

    with pytest.raises(HarnessValidationError):
        HarnessWorkflowSpec(workflow_id="research", steps=(step, step), entry_step_id="collect")


def test_workflow_spec_rejects_unknown_routing_step() -> None:
    step = HarnessStepSpec(step_id="collect", worker_type="llm")

    with pytest.raises(HarnessValidationError):
        HarnessWorkflowSpec(
            workflow_id="research",
            steps=(step,),
            entry_step_id="collect",
            routing_rules=(HarnessRoutingRule(from_step="collect", to_step="missing"),),
        )


def test_run_spec_requires_harness_workflow_and_budget() -> None:
    with pytest.raises(HarnessValidationError):
        HarnessRunSpec(run_id="run-1", workflow=object())  # type: ignore[arg-type]

    workflow = _workflow()
    with pytest.raises(HarnessValidationError):
        HarnessRunSpec(run_id="run-1", workflow=workflow, budget=object())  # type: ignore[arg-type]


def test_budget_rejects_missing_or_illegal_core_limits() -> None:
    with pytest.raises(HarnessValidationError):
        HarnessBudget(max_turns=0, max_replans=1, max_retries_per_step=1, max_worker_calls=1)

    with pytest.raises(HarnessValidationError):
        HarnessBudget(max_turns=1, max_replans=-1, max_retries_per_step=1, max_worker_calls=1)


def test_initial_state_builds_step_states_from_workflow() -> None:
    run_spec = HarnessRunSpec(run_id="run-1", workflow=_workflow())
    state = HarnessState.initial(run_spec)

    assert state.current_step_id == "collect"
    assert [step_state.step_id for step_state in state.step_states] == ["collect"]
    assert state.to_dict()["run_spec"]["budget"]["max_turns"] == HarnessBudget.safe_default().max_turns


def test_decision_must_be_owned_by_harness() -> None:
    decision = HarnessDecision(
        decision_type=HarnessDecisionType.PLAN_STEP,
        run_id="run-1",
        step_id="collect",
    )
    assert decision.to_dict()["decided_by"] == "harness"

    with pytest.raises(HarnessValidationError):
        HarnessDecision(decision_type="complete_run", run_id="run-1", decided_by="llm")


def test_framework_harness_has_no_forbidden_imports() -> None:
    root = Path("framework/harness")
    forbidden_prefixes = ("business", "interfaces", "infrastructure", "framework.agent.harness")
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for imported in _imports_for_file(path):
            if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in forbidden_prefixes):
                violations.append(f"{path.as_posix()}: {imported}")

    assert violations == []


def _workflow() -> HarnessWorkflowSpec:
    step = HarnessStepSpec(
        step_id="collect",
        worker_type="llm",
        input_keys=("paper",),
        output_key="candidate",
        retry_policy=HarnessRetryPolicy(max_retries=1),
        quality_gate="candidate_schema",
    )
    return HarnessWorkflowSpec(workflow_id="research", steps=(step,), entry_step_id="collect")


def _imports_for_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports
