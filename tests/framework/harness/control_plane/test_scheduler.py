from __future__ import annotations

from framework.harness import (
    DeterministicGate,
    DeterministicGateRegistry,
    GateContext,
    GateReference,
    GateRegistration,
    HarnessBudget,
    HarnessControlPlane,
    HarnessEventType,
    HarnessGateResult,
    HarnessGraphDecisionType,
    InMemoryHarnessEventPort,
    HarnessRetryPolicy,
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessStepSpec,
    HarnessStepStatus,
    HarnessWorkerResult,
)
from framework.harness.workflow.spec import (
    HarnessRouteKind,
    HarnessRoutingRule,
    HarnessWorkflowSpec,
)


class _RoutingQualityGate(DeterministicGate):
    gate_name = "routing_quality"

    def evaluate(self, context: GateContext) -> HarnessGateResult:
        return HarnessGateResult(
            gate_name=self.gate_name,
            passed=True,
            details={"score": 0.95},
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
    event_port = InMemoryHarnessEventPort()
    result = HarnessControlPlane(
        event_port=event_port,
        worker_registry={
            "collect": lambda task: HarnessWorkerResult(status="succeeded", output={"claim": "grounded"}),
            "summarize": lambda task: HarnessWorkerResult(status="succeeded", output={"summary": "done"}),
        }
    ).run(HarnessRunSpec(run_id="run-linear", workflow=workflow))

    assert result.state.status == HarnessRunStatus.SUCCEEDED
    assert [decision.decision_type for decision in result.decisions] == [
        HarnessGraphDecisionType.ACTIVATE_NODE,
        HarnessGraphDecisionType.ENTER_STEP_PHASE,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT,
        HarnessGraphDecisionType.COMPLETE_NODE,
        HarnessGraphDecisionType.ACTIVATE_NODE,
        HarnessGraphDecisionType.ENTER_STEP_PHASE,
        HarnessGraphDecisionType.DISPATCH_ACTIVITY,
        HarnessGraphDecisionType.VERIFY_ACTIVITY_RESULT,
        HarnessGraphDecisionType.COMPLETE_NODE,
        HarnessGraphDecisionType.COMPLETE_RUN,
    ]
    phase_events = [event for event in result.events if event.event_type == HarnessEventType.PHASE_RECORDED]
    assert [(event.step_id, event.payload["phase"], event.payload["boundary"]) for event in phase_events] == [
        ("collect", "plan", "entry"),
        ("collect", "plan", "exit"),
        ("collect", "execute", "entry"),
        ("collect", "execute", "exit"),
        ("collect", "verify", "entry"),
        ("collect", "verify", "exit"),
        ("summarize", "plan", "entry"),
        ("summarize", "plan", "exit"),
        ("summarize", "execute", "entry"),
        ("summarize", "execute", "exit"),
        ("summarize", "verify", "entry"),
        ("summarize", "verify", "exit"),
    ]
    recovery = event_port.recover_graph(result.state.run_spec.run_id)
    assert tuple(commit.decision for commit in recovery.decision_commits) == tuple(
        result.decisions
    )
    assert recovery.pending_decisions == ()
    assert len(
        {commit.decision.decision_checksum for commit in recovery.decision_commits}
    ) == len(result.decisions)
    projection_sequences = {
        commit.cause_checksum: commit.sequence
        for commit in recovery.projection_commits
    }
    assert all(
        commit.sequence
        < projection_sequences[commit.decision.decision_checksum]
        for commit in recovery.decision_commits
    )


def test_worker_waiting_approval_status_cannot_create_approval_state() -> None:
    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "draft": lambda task: HarnessWorkerResult(
                status="waiting_approval",
                output={"approval_observation": {"requested": True}},
            )
        },
    ).run(
        HarnessRunSpec(
            run_id="run-worker-approval-request",
            workflow=HarnessWorkflowSpec(
                workflow_id="worker-approval-request",
                steps=(HarnessStepSpec(step_id="draft", worker_type="llm"),),
                entry_step_id="draft",
            ),
        )
    )

    assert result.state.status == HarnessRunStatus.HALTED
    assert all(
        decision.decision_type is not HarnessGraphDecisionType.REGISTER_WAIT
        for decision in result.decisions
    )
    assert result.state.metadata["terminal_reason"] == (
        "worker_approval_request_untrusted"
    )
    halt = result.decisions[-1]
    assert halt.decision_type is HarnessGraphDecisionType.HALT_RUN
    assert halt.payload["reason"] == "worker requested approval without Harness policy"


def test_routing_rule_jumps_to_declared_step() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="route",
        steps=(
            HarnessStepSpec(
                step_id="classify",
                worker_type="llm",
                output_key="classification",
                quality_gate="routing_quality@1",
            ),
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
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "classify": lambda task: HarnessWorkerResult(status="succeeded", output={"classification": "repair"}),
            "repair": lambda task: HarnessWorkerResult(status="succeeded", output={"fixed": True}),
            "normal_path": lambda task: HarnessWorkerResult(status="succeeded", output={"normal": True}),
        },
        gate_registry=DeterministicGateRegistry(
            (
                GateRegistration(
                    reference=GateReference.parse("routing_quality@1"),
                    gate=_RoutingQualityGate(),
                ),
            )
        ),
    ).run(HarnessRunSpec(run_id="run-route", workflow=workflow))

    routed = [
        decision
        for decision in result.decisions
        if decision.decision_type is HarnessGraphDecisionType.SELECT_CHOICE
    ]
    assert routed[0].target_node_ids == ("repair",)
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
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "draft": lambda task: HarnessWorkerResult(status="succeeded", output={"body": "missing title"}),
            "repair": lambda task: HarnessWorkerResult(status="succeeded", output={"title": "fixed"}),
        }
    ).run(HarnessRunSpec(run_id="run-repair", workflow=workflow))

    repair_decisions = [
        decision
        for decision in result.decisions
        if decision.decision_type is HarnessGraphDecisionType.ROUTE_TO_REPAIR
    ]
    assert repair_decisions[0].target_node_ids == ("repair",)
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
        event_port=InMemoryHarnessEventPort(),
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
        event_port=InMemoryHarnessEventPort(),
        worker_registry={"collect": lambda task: HarnessWorkerResult(status="succeeded", output={"ok": True})}
    ).run(
        HarnessRunSpec(
            run_id="run-turn-budget",
            workflow=workflow,
            budget=HarnessBudget(max_turns=2, max_replans=0, max_retries_per_step=0, max_worker_calls=10),
        )
    )

    assert result.state.status == HarnessRunStatus.HALTED
    assert result.state.metadata["terminal_reason"] == "turn_budget_exhausted"
    halt = result.decisions[-1]
    assert halt.decision_type is HarnessGraphDecisionType.HALT_RUN
    assert halt.payload["reason"] == "turn budget is exhausted"
