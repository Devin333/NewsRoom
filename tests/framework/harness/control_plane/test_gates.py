from __future__ import annotations

from dataclasses import replace

import pytest

from framework.harness import (
    CumulativeLLMBudgetGate,
    DeduplicationGate,
    GateContext,
    HarnessBudgetSnapshot,
    HarnessCumulativeBudgetFact,
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


def test_cumulative_budget_gate_uses_verified_fact_only() -> None:
    state, step = _state_and_step(HarnessStepSpec(step_id="budget", worker_type="llm"))
    allowed = CumulativeLLMBudgetGate().evaluate(
        _context(state, step, cumulative_budget_fact=_budget_fact())
    )
    denied = CumulativeLLMBudgetGate().evaluate(
        _context(
            state,
            step,
            cumulative_budget_fact=_budget_fact(
                event_type="budget_reservation_denied",
                within_budget=False,
                violations=("max_llm_calls",),
            ),
        )
    )
    invalid = CumulativeLLMBudgetGate().evaluate(
        _context(
            state,
            step,
            cumulative_budget_fact=_budget_fact(
                resolution_status="invalid",
                within_budget=False,
                event_type=None,
                reason_code="budget_fact_history_invalid",
            ),
        )
    )

    assert allowed.passed is True
    assert allowed.details["reason_code"] == "cumulative_llm_budget_verified"
    assert denied.passed is False
    assert denied.details["reason_code"] == "cumulative_llm_budget_denied"
    assert invalid.passed is False
    assert invalid.details["reason_code"] == "budget_fact_history_invalid"


def test_cumulative_budget_fact_rejects_unbounded_violations() -> None:
    with pytest.raises(ValueError, match="supported bound"):
        _budget_fact(violations=tuple(f"reason-{index}" for index in range(17)))


def _state_and_step(step: HarnessStepSpec) -> tuple[HarnessState, HarnessStepSpec]:
    workflow = HarnessWorkflowSpec(workflow_id=f"wf-{step.step_id}", steps=(step,), entry_step_id=step.step_id)
    state = HarnessState.initial(HarnessRunSpec(run_id=f"run-{step.step_id}", workflow=workflow))
    return state, step


def _context(
    state: HarnessState,
    step: HarnessStepSpec,
    worker_result: HarnessWorkerResult | None = None,
    cumulative_budget_fact: HarnessCumulativeBudgetFact | None = None,
) -> GateContext:
    return GateContext(
        state=state,
        step_spec=step,
        step_state=get_step_state(state, step.step_id),
        worker_result=worker_result,
        budget=HarnessBudgetSnapshot.from_budget(state.run_spec.budget),
        cumulative_budget_fact=cumulative_budget_fact,
    )


def _budget_fact(
    *,
    resolution_status: str = "verified",
    event_type: str | None = "budget_reservation_settled",
    within_budget: bool = True,
    violations: tuple[str, ...] = (),
    reason_code: str | None = None,
) -> HarnessCumulativeBudgetFact:
    verified = resolution_status == "verified"
    return HarnessCumulativeBudgetFact(
        resolution_status=resolution_status,
        operation_id="operation-1",
        ledger_revision=2,
        within_budget=within_budget,
        violations=violations,
        fact_ref="sha256:" + "a" * 64 if verified else None,
        event_id="event-2" if verified else None,
        event_type=event_type if verified else None,
        reservation_id=(
            None if event_type == "budget_reservation_denied" else "reservation-1"
        ),
        policy_digest="sha256:" + "b" * 64 if verified else None,
        scope_id="run-budget:root" if verified else None,
        stream_sequence=2 if verified else None,
        reason_code=reason_code,
    )
