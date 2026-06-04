from __future__ import annotations

from dataclasses import replace

from framework.harness import (
    DeduplicationGate,
    GateContext,
    HarnessBudgetSnapshot,
    HarnessRunSpec,
    HarnessState,
    HarnessStepSpec,
    HarnessWorkerResult,
    HarnessWorkflowSpec,
    ScoreRangeGate,
    ToolAllowlistGate,
)
from framework.harness.control_plane.transitions import get_step_state


def test_tool_allowlist_gate_rejects_unauthorized_tool() -> None:
    state, step = _state_and_step(
        HarnessStepSpec(
            step_id="collect",
            worker_type="llm",
            metadata={"tool_allowlist": ("search",), "requested_tools": ("search", "shell")},
        )
    )
    result = ToolAllowlistGate().evaluate(_context(state, step))

    assert result.passed is False
    assert result.details["denied"] == ["shell"]


def test_deduplication_gate_rejects_duplicate_plan_key() -> None:
    state, step = _state_and_step(HarnessStepSpec(step_id="plan", worker_type="llm"))
    state = replace(state, metadata={**state.metadata, "plan_keys": ("same-plan",)})
    result = DeduplicationGate().evaluate(
        _context(
            state,
            step,
            HarnessWorkerResult(status="succeeded", output={"plan_key": "same-plan"}),
        )
    )

    assert result.passed is False
    assert result.reason == "duplicate plan key"


def test_score_range_gate_rejects_score_outside_configured_range() -> None:
    state, step = _state_and_step(
        HarnessStepSpec(
            step_id="score",
            worker_type="llm",
            metadata={"score_ranges": {"rating": {"min": 1, "max": 5}}},
        )
    )
    result = ScoreRangeGate().evaluate(
        _context(
            state,
            step,
            HarnessWorkerResult(status="succeeded", output={"rating": 6}),
        )
    )

    assert result.passed is False
    assert result.details["violations"]["rating"] == {"value": 6, "min": 1.0, "max": 5.0}


def _state_and_step(step: HarnessStepSpec) -> tuple[HarnessState, HarnessStepSpec]:
    workflow = HarnessWorkflowSpec(workflow_id=f"wf-{step.step_id}", steps=(step,), entry_step_id=step.step_id)
    state = HarnessState.initial(HarnessRunSpec(run_id=f"run-{step.step_id}", workflow=workflow))
    return state, step


def _context(
    state: HarnessState,
    step: HarnessStepSpec,
    worker_result: HarnessWorkerResult | None = None,
) -> GateContext:
    return GateContext(
        state=state,
        step_spec=step,
        step_state=get_step_state(state, step.step_id),
        worker_result=worker_result,
        budget=HarnessBudgetSnapshot.from_budget(state.run_spec.budget),
    )
