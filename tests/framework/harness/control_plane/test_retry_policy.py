from __future__ import annotations

from framework.harness import (
    HarnessBudget,
    HarnessControlPlane,
    InMemoryHarnessEventPort,
    HarnessRetryPolicy,
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessStepSpec,
    HarnessStepStatus,
    HarnessWorkerResult,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec


def test_retry_exhaustion_fails_run() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="retry",
        steps=(
            HarnessStepSpec(
                step_id="call",
                worker_type="llm",
                retry_policy=HarnessRetryPolicy(max_attempts=2, retry_on_statuses=("failed",)),
            ),
        ),
        entry_step_id="call",
    )
    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "call": (
                HarnessWorkerResult(status="failed", error="first failure"),
                HarnessWorkerResult(status="failed", error="second failure"),
            )
        }
    ).run(
        HarnessRunSpec(
            run_id="run-retry",
            workflow=workflow,
            budget=HarnessBudget(max_turns=20, max_replans=0, max_retries_per_step=5, max_worker_calls=10),
        )
    )

    step_state = next(step for step in result.state.step_states if step.step_id == "call")
    assert result.state.status == HarnessRunStatus.FAILED
    assert step_state.status == HarnessStepStatus.FAILED
    assert step_state.attempts == 2
    assert result.state.metadata["terminal_reason"] == "graph_terminal_failure"
    assert result.graph_state is not None
    failed_node = next(
        node
        for node in result.graph_state.node_instances
        if node.step_id == "call"
    )
    assert failed_node.metadata["decision_payload"]["reason"] == "second failure"
    assert failed_node.metadata["decision_payload"]["error"] == "second failure"


def test_global_retry_budget_caps_step_policy_attempts() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="retry-budget",
        steps=(
            HarnessStepSpec(
                step_id="call",
                worker_type="llm",
                retry_policy=HarnessRetryPolicy(max_attempts=5, retry_on_statuses=("failed",)),
            ),
        ),
        entry_step_id="call",
    )
    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "call": (
                HarnessWorkerResult(status="failed", error="first failure"),
                HarnessWorkerResult(status="failed", error="second failure"),
            )
        }
    ).run(
        HarnessRunSpec(
            run_id="run-retry-global",
            workflow=workflow,
            budget=HarnessBudget(max_turns=20, max_replans=0, max_retries_per_step=1, max_worker_calls=10),
        )
    )

    step_state = next(step for step in result.state.step_states if step.step_id == "call")
    assert result.state.status == HarnessRunStatus.FAILED
    assert step_state.attempts == 2


def test_fail_fast_error_type_skips_retry() -> None:
    workflow = HarnessWorkflowSpec(
        workflow_id="fail-fast",
        steps=(
            HarnessStepSpec(
                step_id="call",
                worker_type="llm",
                retry_policy=HarnessRetryPolicy(
                    max_attempts=3,
                    retry_on_statuses=("failed",),
                    fail_fast_error_types=("policy_violation",),
                ),
            ),
        ),
        entry_step_id="call",
    )
    result = HarnessControlPlane(
        event_port=InMemoryHarnessEventPort(),
        worker_registry={
            "call": lambda task: HarnessWorkerResult(
                status="failed",
                error="policy denied",
                diagnostics={"error_type": "policy_violation"},
            )
        }
    ).run(
        HarnessRunSpec(
            run_id="run-fail-fast",
            workflow=workflow,
            budget=HarnessBudget(max_turns=20, max_replans=0, max_retries_per_step=3, max_worker_calls=10),
        )
    )

    step_state = next(step for step in result.state.step_states if step.step_id == "call")
    assert result.state.status == HarnessRunStatus.FAILED
    assert step_state.attempts == 1
