from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from framework.events.canonical import (
    DEFAULT_MAX_EXTENSION_BYTES,
    PayloadReference,
    canonical_json_bytes,
    checksum_for,
)
from framework.events.runtime.activities import (
    ReplayActivityDescriptor,
    ReplayActivityKind,
    ReplayActivityOutcome,
    ReplayActivityStatus,
    ResolvedReplayActivity,
)
from framework.events.schema.security import SecurityClassification
from framework.events.runtime.history import (
    DeterministicCommand,
    HistoryCommandMismatchError,
)
from framework.events.runtime.replay_engine import ReplayEvent
from framework.harness.control_plane.decision import (
    HarnessDecision,
    HarnessDecisionType,
)
from framework.harness.control_plane.replay_history import (
    build_harness_history_verifier,
    harness_decision_kernel,
    harness_decision_history,
    harness_decision_input_snapshot,
)
from framework.harness.control_plane.state import (
    HarnessRunSpec,
    HarnessRunStatus,
    HarnessState,
    HarnessStepStatus,
)
from framework.harness.side_effects import HarnessTerminalSideEffectPolicy
from framework.harness.workflow.spec import (
    HarnessRouteKind,
    HarnessRoutingRule,
    HarnessWorkflowSpec,
)
from framework.harness.workflow.step import HarnessStepSpec


NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


def _approval_checkpoint() -> dict[str, object]:
    return {
        "next_sequence": 5,
        "next_command_ordinal": 4,
        "history_checksum": checksum_for("history-through-command-3"),
        "pinned_versions": [],
    }


def _state() -> HarnessState:
    run_spec = HarnessRunSpec(
        run_id="run-replay-history",
        workflow=HarnessWorkflowSpec(
            workflow_id="replay-history",
            steps=(HarnessStepSpec(step_id="collect", worker_type="llm"),),
            entry_step_id="collect",
            metadata={"version": "1"},
        ),
        created_at=NOW,
    )
    return HarnessState.initial(run_spec)


def test_terminal_side_effect_policy_uses_bounded_decision_projection() -> None:
    policy = HarnessTerminalSideEffectPolicy(
        policy_id="research.publication",
        version="1",
        handler="research.artifact.bundle@1",
        kind="research.artifact.bundle",
        requires_approval=False,
        retry_limit=1,
        not_required_evidence_ref=checksum_for("not-required"),
        inherited_gate_refs=("ResearchQualityGate@1",),
    )
    state = HarnessState.initial(
        HarnessRunSpec(
            run_id="run-terminal-policy-projection",
            workflow=HarnessWorkflowSpec(
                workflow_id="terminal-policy-projection",
                steps=(
                    HarnessStepSpec(step_id="collect", worker_type="llm"),
                    HarnessStepSpec(step_id="publish", worker_type="artifact"),
                    HarnessStepSpec(step_id="cleanup", worker_type="script"),
                ),
                entry_step_id="collect",
                terminal_side_effect_policy=policy,
            ),
            created_at=NOW,
        )
    )

    snapshot = harness_decision_input_snapshot(
        state=state,
        command_ordinal=0,
        causation_id="harness-run:run-terminal-policy-projection",
    )
    projection = snapshot["current_step_policy"]["terminal_side_effect_policy"]

    assert projection == {
        "reference": policy.reference,
        "checksum": checksum_for(policy.to_dict()),
        "handler": policy.handler.to_dict(),
        "kind": policy.kind,
    }
    assert len(canonical_json_bytes(projection)) < len(
        canonical_json_bytes(policy.to_dict())
    )
    assert snapshot["step_order"] == ("collect", "publish")


def _event(
    *,
    recorded: DeterministicCommand | None = None,
) -> ReplayEvent:
    state = _state()
    handler_input = harness_decision_input_snapshot(
        state=state,
        command_ordinal=0,
        causation_id="harness-run:run-replay-history",
    )
    decision = HarnessDecision(
        decision_type=HarnessDecisionType.START_STEP,
        run_id=state.run_spec.run_id,
        step_id="collect",
        target_step_id="collect",
        reason="start entry step",
        decided_at=NOW,
    )
    history = harness_decision_history(
        workflow_id=state.run_spec.workflow.workflow_id,
        workflow_version="1",
        command_ordinal=0,
        decision_input=handler_input,
        decision=decision,
        causation_id="harness-run:run-replay-history",
    )
    if recorded is not None:
        history = replace(history, commands=(recorded,))
    return ReplayEvent(
        event_id="decision-1",
        event_type="decision_recorded",
        source_data_schema="newsroom.harness-event/v1",
        data_schema="newsroom.harness-event/v1",
        stream_id="run:run-replay-history",
        stream_sequence=1,
        occurred_at="2026-07-16T12:00:00Z",
        payload={"decision_type": "start_step"},
        record_checksum=checksum_for("decision-1"),
        history=history.to_dict(),
    )


def _approval_event(*, approved: bool) -> ReplayEvent:
    initial = _state()
    state = replace(
        initial,
        status=HarnessRunStatus.WAITING_APPROVAL,
        step_states=(
            replace(
                initial.step_states[0],
                status=HarnessStepStatus.WAITING_APPROVAL,
            ),
        ),
    )
    outcome = "approved" if approved else "cancelled"
    decision_type = (
        HarnessDecisionType.RESUME_AFTER_APPROVAL
        if approved
        else HarnessDecisionType.CANCEL_RUN
    )
    handler_input = harness_decision_input_snapshot(
        state=state,
        command_ordinal=4,
        causation_id="approval-request-1",
        approval_outcome=outcome,
    )
    history = harness_decision_history(
        workflow_id=state.run_spec.workflow.workflow_id,
        workflow_version="1",
        command_ordinal=4,
        decision_input=handler_input,
        decision=HarnessDecision(
            decision_type=decision_type,
            run_id=state.run_spec.run_id,
            step_id="collect",
            payload={"approval_outcome": outcome},
            decided_at=NOW,
        ),
        causation_id="approval-request-1",
    )
    return ReplayEvent(
        event_id=f"approval-{outcome}",
        event_type="decision_recorded",
        source_data_schema="newsroom.harness-event/v1",
        data_schema="newsroom.harness-event/v1",
        stream_id="run:run-replay-history",
        stream_sequence=5,
        occurred_at="2026-07-16T12:00:00Z",
        payload={"decision_type": decision_type.value},
        record_checksum=checksum_for(f"approval-{outcome}"),
        history=history.to_dict(),
    )


def test_harness_verifier_reexecutes_pure_decision_kernel() -> None:
    verifier = build_harness_history_verifier(
        workflow_id="replay-history",
        workflow_version="1",
    )

    session = verifier.start().verify_event(_event())

    assert session.state.next_command_ordinal == 1


def test_decision_snapshot_compaction_preserves_kernel_and_extension_budget() -> None:
    steps = tuple(
        HarnessStepSpec(
            step_id=f"bounded-replay-step-{index:02d}",
            worker_type="llm",
        )
        for index in range(48)
    )
    routing_rules = tuple(
        HarnessRoutingRule(from_step=left.step_id, to_step=right.step_id)
        for left, right in zip(steps, steps[1:])
    )
    run_spec = HarnessRunSpec(
        run_id="run-bounded-replay-history",
        workflow=HarnessWorkflowSpec(
            workflow_id="bounded-replay-history",
            steps=steps,
            entry_step_id=steps[0].step_id,
            routing_rules=routing_rules,
            metadata={"version": "1"},
        ),
        created_at=NOW,
    )
    state = HarnessState.initial(run_spec)
    compact = dict(
        harness_decision_input_snapshot(
            state=state,
            command_ordinal=0,
            causation_id="harness-run:run-bounded-replay-history",
        )
    )
    full = {
        **compact,
        "routing_rules": tuple(rule.to_dict() for rule in routing_rules),
        "step_states": tuple(
            {
                "step_id": step.step_id,
                "status": step.status.value,
                "attempts": step.attempts,
                "replans": step.replans,
                "approval_granted": bool(step.metadata.get("approval_granted")),
            }
            for step in state.step_states
        ),
    }

    compact_decision = harness_decision_kernel(compact, None)
    assert harness_decision_kernel(full, None) == compact_decision
    assert compact["before_state_checksum"] == full["before_state_checksum"]
    assert [item["step_id"] for item in compact["step_states"]] == [
        steps[0].step_id
    ]
    assert [item["from_step"] for item in compact["routing_rules"]] == [
        steps[0].step_id
    ]

    decision = HarnessDecision(
        decision_type=compact_decision["decision_type"],
        run_id=run_spec.run_id,
        step_id=compact_decision["step_id"],
        target_step_id=compact_decision["target_step_id"],
        reason=compact_decision["reason"],
        payload=dict(compact_decision["payload"]),
        decided_at=NOW,
    )
    compact_history = harness_decision_history(
        workflow_id=run_spec.workflow.workflow_id,
        workflow_version="1",
        command_ordinal=0,
        decision_input=compact,
        decision=decision,
        causation_id="harness-run:run-bounded-replay-history",
    )
    full_history = harness_decision_history(
        workflow_id=run_spec.workflow.workflow_id,
        workflow_version="1",
        command_ordinal=0,
        decision_input=full,
        decision=decision,
        causation_id="harness-run:run-bounded-replay-history",
    )
    compact_size = len(
        canonical_json_bytes({"deterministic_history": compact_history.to_dict()})
    )
    full_size = len(
        canonical_json_bytes({"deterministic_history": full_history.to_dict()})
    )

    assert full_size > DEFAULT_MAX_EXTENSION_BYTES
    assert compact_size <= DEFAULT_MAX_EXTENSION_BYTES


def test_recorded_transition_output_cannot_drive_expected_decision() -> None:
    baseline = _event()
    command = baseline.history["commands"][0]
    wrong = DeterministicCommand(
        ordinal=command["ordinal"],
        kind="halt_run",
        target=command["target"],
        handler_version=command["handler_version"],
        workflow_version=command["workflow_version"],
        policy_version=command["policy_version"],
        input_refs=tuple(command["input_refs"]),
        input_checksums=tuple(command["input_checksums"]),
        budget_ref=command["budget_ref"],
        gate_ref=command["gate_ref"],
        decision_ref=checksum_for({"changed": "recorded-output-only"}),
        causation_id=command["causation_id"],
    )
    verifier = build_harness_history_verifier(
        workflow_id="replay-history",
        workflow_version="1",
    )

    with pytest.raises(HistoryCommandMismatchError) as caught:
        verifier.start().verify_event(_event(recorded=wrong))

    assert caught.value.reason_class == "command_nondeterminism"
    assert caught.value.details["mismatch_kind"] in {"type", "content"}


@pytest.mark.parametrize(
    ("approved", "expected_kind"),
    [
        (True, HarnessDecisionType.RESUME_AFTER_APPROVAL),
        (False, HarnessDecisionType.CANCEL_RUN),
    ],
)
def test_approval_outcome_rebuilds_the_recorded_command(
    approved: bool,
    expected_kind: HarnessDecisionType,
) -> None:
    verifier = build_harness_history_verifier(
        workflow_id="replay-history",
        workflow_version="1",
    )

    session = verifier.start(_approval_checkpoint()).verify_event(
        _approval_event(approved=approved)
    )

    assert session.state.next_command_ordinal == 5
    assert _approval_event(approved=approved).history["commands"][0][
        "kind"
    ] == expected_kind.value


def test_approval_outcome_is_required_to_rebuild_resume_or_cancel() -> None:
    event = _approval_event(approved=True)
    history = event.history
    handler_input = dict(history["handler_input"])
    handler_input["approval_outcome"] = None
    tampered_history = harness_decision_history(
        workflow_id="replay-history",
        workflow_version="1",
        command_ordinal=4,
        decision_input=handler_input,
        decision=HarnessDecision(
            decision_type=HarnessDecisionType.RESUME_AFTER_APPROVAL,
            run_id="run-replay-history",
            step_id="collect",
            payload={"approval_outcome": "approved"},
            decided_at=NOW,
        ),
        causation_id="approval-request-1",
    )
    tampered_event = replace(event, history=tampered_history.to_dict())
    verifier = build_harness_history_verifier(
        workflow_id="replay-history",
        workflow_version="1",
    )

    with pytest.raises(HistoryCommandMismatchError) as caught:
        verifier.start(_approval_checkpoint()).verify_event(tampered_event)

    assert caught.value.reason_class == "command_nondeterminism"


def test_verifier_requires_exact_activity_version_allowlist() -> None:
    verifier = build_harness_history_verifier(
        workflow_id="replay-history",
        workflow_version="1",
    )

    assert verifier is not None


def _resolved_worker_activity(
    status: str,
    *,
    error_type: str | None = None,
) -> ResolvedReplayActivity:
    input_ref = PayloadReference(
        uri="secure-activity://tenant-test/input",
        expected_checksum=checksum_for({"input": "accepted"}),
    )
    descriptor = ReplayActivityDescriptor(
        activity_id="activity-routing",
        activity_kind=ReplayActivityKind.LLM,
        input_ref=input_ref,
        input_checksum=input_ref.expected_checksum,
        idempotency_key="activity:routing",
        attempt=1,
        contract_version="newsroom.harness-worker-activity/v1",
        handler_version="1",
        accepted_at=NOW,
        context={
            "run_id": "run-replay-history",
            "step_id": "collect",
            "activity_type": "llm",
            "identity_scope_ref": None,
            "worker_status": status,
            "worker_error_type": error_type,
        },
        tenant_id="tenant-test",
        security_classification=SecurityClassification.CONFIDENTIAL,
    )
    output_ref = PayloadReference(
        uri="secure-activity://tenant-test/output",
        expected_checksum=checksum_for({"status": status}),
    )
    succeeded = status == "succeeded"
    outcome = ReplayActivityOutcome(
        activity_id=descriptor.activity_id,
        status=(
            ReplayActivityStatus.SUCCEEDED
            if succeeded
            else ReplayActivityStatus.FAILED
        ),
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        output_ref=output_ref if succeeded else None,
        output_checksum=output_ref.expected_checksum if succeeded else None,
        error_class=None if succeeded else f"harness_worker_{status}",
        error_ref=None if succeeded else output_ref,
    )
    return ResolvedReplayActivity(
        activity=descriptor,
        outcome=outcome,
        pinned_version=descriptor.pinned_version,
        recorded_ref=PayloadReference(
            uri="secure-activity://tenant-test/record",
            expected_checksum=checksum_for({"record": status}),
        ),
    )


@pytest.mark.parametrize(
    ("status", "expected_decision"),
    [
        ("failed", "retry_step"),
        ("blocked", "block_run"),
        ("waiting_approval", "wait_for_approval"),
    ],
)
def test_pure_kernel_routes_from_recorded_worker_status(
    status: str,
    expected_decision: str,
) -> None:
    state = _state()
    state = replace(
        state,
        status=HarnessRunStatus.EXECUTING,
        current_step_id="collect",
        step_states=(
            replace(
                state.step_states[0],
                status=HarnessStepStatus.RUNNING,
                attempts=1,
            ),
        ),
    )
    state = replace(
        state,
        run_spec=replace(
            state.run_spec,
            workflow=replace(
                state.run_spec.workflow,
                steps=(
                    replace(
                        state.run_spec.workflow.steps[0],
                        retry_policy=replace(
                            state.run_spec.workflow.steps[0].retry_policy,
                            max_attempts=2,
                        ),
                    ),
                ),
            ),
        ),
    )
    decision_input = harness_decision_input_snapshot(
        state=state,
        command_ordinal=0,
        causation_id="activity-result",
        expected_activity=_resolved_worker_activity(status).activity,
    )

    decision = harness_decision_kernel(
        decision_input,
        _resolved_worker_activity(status),
    )

    assert decision["decision_type"] == expected_decision


def test_on_status_route_uses_recorded_activity_not_snapshot_worker_status() -> None:
    initial = _state()
    workflow = HarnessWorkflowSpec(
        workflow_id="replay-history",
        steps=(
            HarnessStepSpec(step_id="collect", worker_type="llm"),
            HarnessStepSpec(step_id="status-path", worker_type="llm"),
            HarnessStepSpec(step_id="default-path", worker_type="llm"),
        ),
        entry_step_id="collect",
        routing_rules=(
            HarnessRoutingRule(
                from_step="collect",
                to_step="status-path",
                kind=HarnessRouteKind.ON_STATUS,
                condition={"status": "succeeded"},
            ),
        ),
        metadata={"version": "1"},
    )
    run_spec = replace(initial.run_spec, workflow=workflow)
    step_states = (
        replace(initial.step_states[0], status=HarnessStepStatus.SUCCEEDED),
        replace(initial.step_states[0], step_id="status-path"),
        replace(initial.step_states[0], step_id="default-path"),
    )
    state = replace(
        initial,
        run_spec=run_spec,
        status=HarnessRunStatus.RUNNING,
        current_step_id="collect",
        step_states=step_states,
    )
    activity = _resolved_worker_activity("succeeded")
    decision_input = harness_decision_input_snapshot(
        state=state,
        command_ordinal=0,
        causation_id="step-success",
        expected_activity=activity.activity,
    )
    assert "worker_result.status" not in decision_input["routing_values"]

    decision = harness_decision_kernel(decision_input, activity)

    assert decision["decision_type"] == "route_to_step"
    assert decision["target_step_id"] == "status-path"
