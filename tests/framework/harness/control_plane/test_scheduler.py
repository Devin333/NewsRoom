from __future__ import annotations

from framework.harness import (
    HarnessBudget,
    HarnessControlPlane,
    HarnessDecisionType,
    HarnessEventType,
    HarnessRetryPolicy,
    HarnessRouteKind,
    HarnessRoutingRule,
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessStepSpec,
    HarnessStepStatus,
    HarnessWorkerResult,
    HarnessWorkflowSpec,
)


def test_linear_workflow_executes_steps_in_order_with_plan_execute_verify() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="linear",
        steps=(
            HarnessStepSpec(step_id="collect", worker_type="llm", output_key="collected"),
            HarnessStepSpec(step_id="summarize", worker_type="llm", output_key="summary"),
        ),
        entry_step_id="collect",
    )
    result = HarnessControlPlane(
        worker_registry={
            "collect": lambda task: HarnessWorkerResult(status="succeeded", output={"claim": "grounded"}),
            "summarize": lambda task: HarnessWorkerResult(status="succeeded", output={"summary": "done"}),
        }
    ).run(HarnessRunSpec(run_id="run-linear", workflow=workflow))

    assert result.state.status == HarnessRunStatus.SUCCEEDED
    assert [decision.decision_type for decision in result.decisions] == [
        HarnessDecisionType.START_STEP,
        HarnessDecisionType.PLAN_STEP,
        HarnessDecisionType.EXECUTE_STEP,
        HarnessDecisionType.VERIFY_STEP,
        HarnessDecisionType.COMPLETE_STEP,
        HarnessDecisionType.ROUTE_TO_STEP,
        HarnessDecisionType.PLAN_STEP,
        HarnessDecisionType.EXECUTE_STEP,
        HarnessDecisionType.VERIFY_STEP,
        HarnessDecisionType.COMPLETE_STEP,
        HarnessDecisionType.COMPLETE_RUN,
    ]
    phase_events = [event for event in result.events if event.event_type == HarnessEventType.PHASE_RECORDED]
    assert [(event.step_id, event.payload["phase"]) for event in phase_events] == [
        ("collect", "plan"),
        ("collect", "execute"),
        ("collect", "verify"),
        ("summarize", "plan"),
        ("summarize", "execute"),
        ("summarize", "verify"),
    ]


def test_routing_rule_jumps_to_declared_step() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="route",
        steps=(
            HarnessStepSpec(step_id="classify", worker_type="llm", output_key="classification"),
            HarnessStepSpec(step_id="normal_path", worker_type="llm", output_key="normal"),
            HarnessStepSpec(step_id="repair", worker_type="llm", output_key="repair"),
        ),
        entry_step_id="classify",
        routing_rules=(
            HarnessRoutingRule(
                from_step="classify",
                to_step="repair",
                kind=HarnessRouteKind.ON_VERDICT,
                condition={"passed": True, "min_score": 0.8},
            ),
        ),
    )
    result = HarnessControlPlane(
        worker_registry={
            "classify": lambda task: HarnessWorkerResult(status="succeeded", output={"quality_score": 0.95}),
            "repair": lambda task: HarnessWorkerResult(status="succeeded", output={"fixed": True}),
            "normal_path": lambda task: HarnessWorkerResult(status="succeeded", output={"normal": True}),
        }
    ).run(HarnessRunSpec(run_id="run-route", workflow=workflow))

    routed = [decision for decision in result.decisions if decision.decision_type == HarnessDecisionType.ROUTE_TO_STEP]
    assert routed[0].target_step_id == "repair"
    assert "normal_path" not in result.worker_results
    assert result.state.status == HarnessRunStatus.SUCCEEDED


def test_quality_gate_failed_routes_to_repair_step() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="quality-repair",
        steps=(
            HarnessStepSpec(
                step_id="draft",
                worker_type="llm",
                output_key="draft",
                retry_policy=HarnessRetryPolicy(repair_step_id="repair"),
                metadata={"output_schema": {"required": ["title"]}},
            ),
            HarnessStepSpec(step_id="repair", worker_type="llm", output_key="repaired"),
        ),
        entry_step_id="draft",
    )
    result = HarnessControlPlane(
        worker_registry={
            "draft": lambda task: HarnessWorkerResult(status="succeeded", output={"body": "missing title"}),
            "repair": lambda task: HarnessWorkerResult(status="succeeded", output={"title": "fixed"}),
        }
    ).run(HarnessRunSpec(run_id="run-repair", workflow=workflow))

    repair_decisions = [decision for decision in result.decisions if decision.decision_type == HarnessDecisionType.ROUTE_TO_REPAIR]
    assert repair_decisions[0].target_step_id == "repair"
    draft_state = next(step for step in result.state.step_states if step.step_id == "draft")
    assert draft_state.status == HarnessStepStatus.FAILED
    assert result.state.status == HarnessRunStatus.SUCCEEDED


def test_max_replans_exhaustion_halts_run() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="replan-budget",
        steps=(
            HarnessStepSpec(
                step_id="draft",
                worker_type="llm",
                output_key="draft",
                metadata={"output_schema": {"required": ["title"]}},
            ),
        ),
        entry_step_id="draft",
    )
    result = HarnessControlPlane(
        worker_registry={"draft": lambda task: HarnessWorkerResult(status="succeeded", output={"body": "missing title"})}
    ).run(
        HarnessRunSpec(
            run_id="run-replan-budget",
            workflow=workflow,
            budget=HarnessBudget(max_turns=20, max_replans=1, max_retries_per_step=1, max_worker_calls=10),
        )
    )

    assert result.state.status == HarnessRunStatus.HALTED
    assert result.state.metadata["terminal_reason"] == "verification failed and replan budget is exhausted"
    assert result.state.replan_count == 1


def test_max_turns_exhaustion_halts_run() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="turn-budget",
        steps=(HarnessStepSpec(step_id="collect", worker_type="llm", output_key="collected"),),
        entry_step_id="collect",
    )
    result = HarnessControlPlane(
        worker_registry={"collect": lambda task: HarnessWorkerResult(status="succeeded", output={"ok": True})}
    ).run(
        HarnessRunSpec(
            run_id="run-turn-budget",
            workflow=workflow,
            budget=HarnessBudget(max_turns=2, max_replans=0, max_retries_per_step=0, max_worker_calls=10),
        )
    )

    assert result.state.status == HarnessRunStatus.HALTED
    assert result.state.metadata["terminal_reason"] == "turn budget is exhausted"
