from __future__ import annotations

import ast
import builtins
import random
import socket
import time
import uuid
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

import framework.harness.control_plane.step_lifecycle as step_lifecycle_module
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.cumulative_budget import HarnessCumulativeBudgetFact
from framework.harness.control_plane.graph_state import (
    HarnessAttemptEvidenceReference,
    HarnessEvidenceKind,
    HarnessNodeInstanceIdentity,
    HarnessNodeInstanceState,
    HarnessNodeInstanceStatus,
)
from framework.harness.control_plane.policy import HarnessBudget, HarnessBudgetSnapshot
from framework.harness.control_plane.state import HarnessStepStatus
from framework.harness.control_plane.step_lifecycle import (
    StepGateObservation,
    StepLifecycleBindingMode,
    StepLifecycleBudget,
    StepLifecycleObservations,
    StepLifecycleState,
    StepLifecycleStateMachine,
    StepLifecycleTransition,
    StepLifecycleTransitionType,
    StepQualityObservation,
    StepWorkerObservation,
)
from framework.harness.graph.activity import HarnessRetryPolicy, HarnessStepSpec
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
    HarnessGraphNodeKind,
)
from framework.harness.graph.versioning import HARNESS_STEP_LIFECYCLE_VERSION
from framework.shared.json import stable_json_dumps


_MACHINE = StepLifecycleStateMachine()


def test_plan_execute_verify_phase_mapping_is_bounded_and_local_to_one_step() -> None:
    step = _step()
    passed_gate = StepGateObservation("schema@1", True)
    cases = (
            (
                HarnessStepStatus.PENDING,
                _observations(attempt=0),
            StepLifecycleTransitionType.PLAN_STEP,
        ),
        (
            HarnessStepStatus.PLANNING,
            _observations(gate_results=(passed_gate,)),
            StepLifecycleTransitionType.EXECUTE_STEP,
        ),
        (
            HarnessStepStatus.PLAN_VERIFIED,
            _observations(),
            StepLifecycleTransitionType.EXECUTE_STEP,
        ),
        (
            HarnessStepStatus.RUNNING,
            _observations(),
            StepLifecycleTransitionType.EXECUTE_STEP,
        ),
        (
            HarnessStepStatus.RUNNING,
            _observations(worker_result=StepWorkerObservation("succeeded")),
            StepLifecycleTransitionType.VERIFY_STEP,
        ),
        (
            HarnessStepStatus.VERIFYING,
            _observations(),
            StepLifecycleTransitionType.VERIFY_STEP,
        ),
        (
            HarnessStepStatus.VERIFYING,
            _observations(gate_results=(passed_gate,)),
            StepLifecycleTransitionType.COMPLETE_STEP,
        ),
        (
            HarnessStepStatus.RETRYING,
            _observations(),
            StepLifecycleTransitionType.EXECUTE_STEP,
        ),
        (
            HarnessStepStatus.REPLANNING,
            _observations(),
            StepLifecycleTransitionType.PLAN_STEP,
        ),
        (
            HarnessStepStatus.WAITING_APPROVAL,
            _observations(),
            StepLifecycleTransitionType.WAIT_FOR_APPROVAL,
        ),
        (
            HarnessStepStatus.HALTED,
            _observations(),
            StepLifecycleTransitionType.HALT_STEP,
        ),
        (
            HarnessStepStatus.FAILED,
            _observations(),
            StepLifecycleTransitionType.FAIL_STEP,
        ),
    )

    for status, observations, expected in cases:
        transition = _MACHINE.next_transition(
            step,
            _state(status),
            observations,
            _budget(),
        )
        assert transition is not None
        assert transition.transition_type is expected
        assert transition.step_id == "draft"
        assert transition.lifecycle_version == HARNESS_STEP_LIFECYCLE_VERSION


@pytest.mark.parametrize(
    ("fact", "expected", "reason_code"),
    (
        (
            HarnessCumulativeBudgetFact(
                resolution_status="verified",
                operation_id="operation-allowed",
                ledger_revision=2,
                within_budget=True,
                violations=(),
                fact_ref="sha256:" + "a" * 64,
                event_id="event-allowed",
                event_type="budget_reservation_settled",
                reservation_id="reservation-allowed",
                policy_digest="sha256:" + "b" * 64,
                scope_id="run-budget:root",
                stream_sequence=2,
            ),
            StepLifecycleTransitionType.VERIFY_STEP,
            "worker_succeeded_verify",
        ),
        (
            HarnessCumulativeBudgetFact(
                resolution_status="verified",
                operation_id="operation-denied",
                ledger_revision=3,
                within_budget=False,
                violations=("max_llm_calls",),
                fact_ref="sha256:" + "c" * 64,
                event_id="event-denied",
                event_type="budget_reservation_denied",
                reservation_id=None,
                policy_digest="sha256:" + "d" * 64,
                scope_id="run-budget:root",
                stream_sequence=3,
            ),
            StepLifecycleTransitionType.HALT_STEP,
            "cumulative_llm_budget_exhausted",
        ),
        (
            HarnessCumulativeBudgetFact(
                resolution_status="verified",
                operation_id="operation-indeterminate",
                ledger_revision=4,
                within_budget=False,
                violations=("dispatch_indeterminate",),
                fact_ref="sha256:" + "e" * 64,
                event_id="event-indeterminate",
                event_type="budget_reservation_indeterminate",
                reservation_id="reservation-indeterminate",
                policy_digest="sha256:" + "f" * 64,
                scope_id="run-budget:root",
                stream_sequence=4,
            ),
            StepLifecycleTransitionType.HALT_STEP,
            "cumulative_llm_budget_indeterminate",
        ),
        (
            HarnessCumulativeBudgetFact(
                resolution_status="invalid",
                operation_id="operation-invalid",
                ledger_revision=5,
                within_budget=False,
                violations=(),
                reason_code="budget_fact_history_invalid",
            ),
            StepLifecycleTransitionType.HALT_STEP,
            "budget_fact_history_invalid",
        ),
    ),
)
def test_canonical_cumulative_budget_fact_controls_post_execute_transition(
    fact: HarnessCumulativeBudgetFact,
    expected: StepLifecycleTransitionType,
    reason_code: str,
) -> None:
    transition = _MACHINE.next_transition(
        _step(),
        _state(HarnessStepStatus.RUNNING),
        _observations(
            worker_result=StepWorkerObservation(
                "succeeded",
                cumulative_budget_fact=fact,
            )
        ),
        _budget(),
    )

    assert transition is not None
    assert transition.transition_type is expected
    assert transition.reason_code == reason_code


@pytest.mark.parametrize(
    "status",
    (HarnessStepStatus.SUCCEEDED, HarnessStepStatus.SKIPPED),
)
def test_terminal_success_or_skip_does_not_select_a_graph_successor(
    status: HarnessStepStatus,
) -> None:
    transition = _MACHINE.next_transition(
        _step(),
        _state(status),
        _observations(
            worker_result=StepWorkerObservation(
                "succeeded",
                candidate_observations={"route": "untrusted-target"},
            )
        ),
        _budget(),
    )

    assert transition is None


def test_graph_node_and_harness_budget_snapshots_are_direct_pure_inputs() -> None:
    checksum = f"sha256:{'a' * 64}"
    node = HarnessNodeInstanceState(
        identity=HarnessNodeInstanceIdentity(
            run_id="run-graph",
            graph_checksum=checksum,
            node_id="draft-node",
            activation_ordinal=1,
        ),
        node_kind=HarnessGraphNodeKind.EXECUTABLE,
        status=HarnessNodeInstanceStatus.READY,
        step_id="draft",
        step_ref=HarnessContractReference(
            HarnessContractKind.STEP,
            "draft",
            "1",
        ),
        step_status=HarnessStepStatus.PENDING,
        activation_sequence=1,
        last_event_sequence=1,
    )
    budget = HarnessBudgetSnapshot.from_budget(HarnessBudget(20, 2, 2, 10))

    transition = _MACHINE.next_transition(
        _step(),
        node,
        StepLifecycleObservations.for_node(node),
        budget,
    )

    assert transition is not None
    assert transition.transition_type is StepLifecycleTransitionType.PLAN_STEP
    assert transition.binding_mode is StepLifecycleBindingMode.GRAPH_BOUND
    assert transition.step_ref == node.step_ref
    assert transition.node_instance_id == node.instance_id
    assert transition.attempt == 0
    assert transition.last_event_sequence == 1


def test_graph_bound_transition_preserves_full_identity_and_evidence_serialization() -> (
    None
):
    identity = _graph_identity()
    worker_evidence = _accepted_evidence(
        identity.instance_id,
        HarnessEvidenceKind.ACTIVITY_RESULT,
        attempt=1,
        event_sequence=2,
        marker="a",
    )
    gate_evidence = _accepted_evidence(
        identity.instance_id,
        HarnessEvidenceKind.GATE_RESULT,
        attempt=1,
        event_sequence=3,
        marker="b",
    )
    quality_evidence = _accepted_evidence(
        identity.instance_id,
        HarnessEvidenceKind.GATE_RESULT,
        attempt=1,
        event_sequence=4,
        marker="c",
    )
    node = _graph_node(
        identity=identity,
        step_status=HarnessStepStatus.VERIFYING,
        attempt=1,
        last_event_sequence=4,
        evidence_refs=(worker_evidence, gate_evidence, quality_evidence),
    )
    input_ref = f"sha256:{'d' * 64}"
    worker = StepWorkerObservation(
        "succeeded",
        candidate_observations={"candidate": {"value": "ok"}},
        accepted_evidence=worker_evidence,
    )
    gate = StepGateObservation(
        "schema",
        True,
        details={
            "harness_gate": {
                "reference": "schema@1",
                "input_ref": input_ref,
                "result_ref": gate_evidence.evidence_ref,
                "reason_code": "schema_passed",
            }
        },
        accepted_evidence=gate_evidence,
    )
    quality = StepQualityObservation(
        True,
        score=1.0,
        metadata={
            "aggregation_version": "1",
            "declared_gate_reference": "schema@1",
            "gate_result_ref": gate_evidence.evidence_ref,
        },
        accepted_evidence=quality_evidence,
    )
    observations = StepLifecycleObservations.for_node(
        node,
        worker_result=worker,
        gate_results=(gate,),
        quality_verdict=quality,
    )
    lifecycle_state = StepLifecycleState.from_node_instance(node)

    transition = _MACHINE.next_transition(
        _step(),
        node,
        observations,
        _budget(),
    )

    assert transition is not None
    assert lifecycle_state.to_dict() == {
        "step_id": "draft",
        "status": "verifying",
        "attempt": 1,
        "replans": 0,
        "error": None,
        "binding_mode": "graph_bound",
        "step_ref": node.step_ref.to_dict(),
        "node_instance_id": identity.instance_id,
        "last_event_sequence": 4,
        "evidence_refs": [
            worker_evidence.to_dict(),
            gate_evidence.to_dict(),
            quality_evidence.to_dict(),
        ],
    }
    assert transition.to_dict() == {
        "transition_type": "complete_step",
        "step_id": "draft",
        "target_step_id": None,
        "reason_code": "verification_passed",
        "reason": None,
        "payload": {},
        "lifecycle_version": HARNESS_STEP_LIFECYCLE_VERSION,
        "binding_mode": "graph_bound",
        "step_ref": node.step_ref.to_dict(),
        "node_instance_id": identity.instance_id,
        "attempt": 1,
        "last_event_sequence": 4,
        "evidence_refs": [
            worker_evidence.to_dict(),
            gate_evidence.to_dict(),
            quality_evidence.to_dict(),
        ],
    }
    assert gate.to_dict() == {
        "gate": "schema",
        "passed": True,
        "reason": None,
        "details": {
            "harness_gate": {
                "reference": "schema@1",
                "input_ref": input_ref,
                "result_ref": gate_evidence.evidence_ref,
                "reason_code": "schema_passed",
            }
        },
        "gate_reference": "schema@1",
        "input_ref": input_ref,
        "result_ref": gate_evidence.evidence_ref,
        "reason_code": "schema_passed",
        "accepted_evidence": gate_evidence.to_dict(),
    }
    assert observations.to_dict() == {
        "binding_mode": "graph_bound",
        "node_instance_id": identity.instance_id,
        "attempt": 1,
        "last_event_sequence": 4,
        "worker_result": worker.to_dict(),
        "gate_results": [gate.to_dict()],
        "quality_verdict": quality.to_dict(),
        "approval_granted": False,
        "approval_evidence": None,
    }


def test_graph_bound_observation_requires_exact_graph_identity() -> None:
    with pytest.raises(HarnessValidationError) as exc_info:
        StepLifecycleObservations()

    assert exc_info.value.code == "missing_step_observation_identity"


@pytest.mark.parametrize(
    ("step_status", "node_status"),
    (
        (HarnessStepStatus.RUNNING, HarnessNodeInstanceStatus.RUNNING),
        (HarnessStepStatus.VERIFYING, HarnessNodeInstanceStatus.RUNNING),
    ),
)
def test_graph_bound_active_phase_rejects_zero_attempt(
    step_status: HarnessStepStatus,
    node_status: HarnessNodeInstanceStatus,
) -> None:
    node = _graph_node(
        step_status=step_status,
        node_status=node_status,
        attempt=0,
    )

    with pytest.raises(HarnessValidationError) as exc_info:
        _MACHINE.next_transition(
            _step(),
            node,
            _observations(),
            _budget(max_retries_per_step=0),
        )

    assert exc_info.value.code == "invalid_step_lifecycle_attempt_state"


def test_graph_bound_observations_reject_sibling_and_cross_attempt_evidence() -> None:
    identity = _graph_identity()
    node_evidence = _accepted_evidence(
        identity.instance_id,
        HarnessEvidenceKind.ACTIVITY_RESULT,
        attempt=1,
        event_sequence=2,
        marker="a",
    )
    node = _graph_node(
        identity=identity,
        step_status=HarnessStepStatus.RUNNING,
        attempt=1,
        last_event_sequence=2,
        evidence_refs=(node_evidence,),
    )
    sibling = _graph_identity(node_id="sibling-node")
    sibling_evidence = _accepted_evidence(
        sibling.instance_id,
        HarnessEvidenceKind.ACTIVITY_RESULT,
        attempt=1,
        event_sequence=2,
        marker="b",
    )
    cross_attempt_evidence = _accepted_evidence(
        identity.instance_id,
        HarnessEvidenceKind.ACTIVITY_RESULT,
        attempt=2,
        event_sequence=2,
        marker="c",
    )

    with pytest.raises(HarnessValidationError) as sibling_error:
        StepLifecycleObservations.for_node(
            node,
            worker_result=StepWorkerObservation(
                "failed",
                accepted_evidence=sibling_evidence,
            ),
        )
    assert sibling_error.value.code == "cross_node_step_evidence_rejected"

    with pytest.raises(HarnessValidationError) as attempt_error:
        StepLifecycleObservations.for_node(
            node,
            worker_result=StepWorkerObservation(
                "failed",
                accepted_evidence=cross_attempt_evidence,
            ),
        )
    assert attempt_error.value.code == "cross_attempt_step_evidence_rejected"


def test_graph_bound_observations_reject_stale_and_unaccepted_evidence() -> None:
    identity = _graph_identity()
    accepted = _accepted_evidence(
        identity.instance_id,
        HarnessEvidenceKind.GATE_RESULT,
        attempt=1,
        event_sequence=3,
        marker="a",
    )
    node = _graph_node(
        identity=identity,
        step_status=HarnessStepStatus.VERIFYING,
        attempt=1,
        last_event_sequence=4,
        evidence_refs=(accepted,),
    )
    gate = _bound_gate(accepted)
    stale = _observations(
        gate_results=(gate,),
        binding_mode=StepLifecycleBindingMode.GRAPH_BOUND,
        node_instance_id=identity.instance_id,
        attempt=1,
        last_event_sequence=3,
    )

    with pytest.raises(HarnessValidationError) as stale_error:
        _MACHINE.next_transition(_step(), node, stale, _budget())
    assert stale_error.value.code == "stale_step_observation_rejected"

    unaccepted = _accepted_evidence(
        identity.instance_id,
        HarnessEvidenceKind.GATE_RESULT,
        attempt=1,
        event_sequence=4,
        marker="b",
    )
    unaccepted_observations = StepLifecycleObservations.for_node(
        node,
        gate_results=(_bound_gate(unaccepted),),
    )
    with pytest.raises(HarnessValidationError) as unaccepted_error:
        _MACHINE.next_transition(
            _step(),
            node,
            unaccepted_observations,
            _budget(),
        )
    assert unaccepted_error.value.code == "unaccepted_step_evidence_rejected"


def test_graph_bound_gate_requires_exact_complete_evidence() -> None:
    identity = _graph_identity()
    evidence = _accepted_evidence(
        identity.instance_id,
        HarnessEvidenceKind.GATE_RESULT,
        attempt=1,
        event_sequence=2,
        marker="a",
    )
    node = _graph_node(
        identity=identity,
        step_status=HarnessStepStatus.VERIFYING,
        attempt=1,
        last_event_sequence=2,
        evidence_refs=(evidence,),
    )

    with pytest.raises(HarnessValidationError) as missing_error:
        StepLifecycleObservations.for_node(
            node,
            gate_results=(
                StepGateObservation(
                    "schema",
                    True,
                    accepted_evidence=evidence,
                ),
            ),
        )
    assert missing_error.value.code == "incomplete_step_gate_evidence"

    with pytest.raises(HarnessValidationError, match="exact"):
        StepGateObservation(
            "schema",
            True,
            gate_reference="schema@latest",
            input_ref=f"sha256:{'b' * 64}",
            result_ref=evidence.evidence_ref,
            gate_reason_code="passed",
            accepted_evidence=evidence,
        )

    with pytest.raises(HarnessValidationError) as mismatch_error:
        StepGateObservation(
            "schema",
            True,
            gate_reference="schema@1",
            input_ref=f"sha256:{'b' * 64}",
            result_ref=f"sha256:{'c' * 64}",
            gate_reason_code="passed",
            accepted_evidence=evidence,
        )
    assert mismatch_error.value.code == "step_gate_evidence_mismatch"


def test_graph_bound_verify_requires_the_declared_gate_identity() -> None:
    identity = _graph_identity()
    evidence = _accepted_evidence(
        identity.instance_id,
        HarnessEvidenceKind.GATE_RESULT,
        attempt=1,
        event_sequence=2,
        marker="f",
    )
    node = _graph_node(
        identity=identity,
        step_status=HarnessStepStatus.VERIFYING,
        attempt=1,
        last_event_sequence=2,
        evidence_refs=(evidence,),
    )
    observations = StepLifecycleObservations.for_node(
        node,
        gate_results=(
            _bound_gate(
                evidence,
                gate_name="other",
                gate_reference="other@1",
            ),
        ),
    )

    with pytest.raises(HarnessValidationError) as captured:
        _MACHINE.next_transition(
            _step(quality_gate="schema@1"),
            node,
            observations,
            _budget(),
        )

    assert captured.value.code == "declared_step_gate_evidence_missing"


@pytest.mark.parametrize(
    ("attempt", "max_retries", "expected"),
    (
        (1, 0, StepLifecycleTransitionType.FAIL_STEP),
        (1, 1, StepLifecycleTransitionType.RETRY_STEP),
        (2, 1, StepLifecycleTransitionType.FAIL_STEP),
    ),
)
def test_graph_bound_retry_budget_exact_boundary(
    attempt: int,
    max_retries: int,
    expected: StepLifecycleTransitionType,
) -> None:
    identity = _graph_identity(activation_ordinal=attempt)
    evidence = _accepted_evidence(
        identity.instance_id,
        HarnessEvidenceKind.ACTIVITY_RESULT,
        attempt=attempt,
        event_sequence=attempt + 1,
        marker=str(attempt),
    )
    node = _graph_node(
        identity=identity,
        step_status=HarnessStepStatus.RUNNING,
        attempt=attempt,
        last_event_sequence=attempt + 1,
        evidence_refs=(evidence,),
    )
    observations = StepLifecycleObservations.for_node(
        node,
        worker_result=StepWorkerObservation(
            "failed",
            error="transient",
            accepted_evidence=evidence,
        ),
    )

    transition = _MACHINE.next_transition(
        _step(retry_policy=HarnessRetryPolicy(max_attempts=5)),
        node,
        observations,
        _budget(
            max_retries_per_step=max_retries,
            worker_calls_used=attempt,
        ),
    )

    assert transition is not None
    assert transition.transition_type is expected
    assert transition.attempt == attempt
    assert transition.evidence_refs == (evidence,)


def test_retry_budget_and_fail_fast_error_type_preserve_current_behavior() -> None:
    retry_policy = HarnessRetryPolicy(
        max_attempts=5,
        retry_on_statuses=("failed",),
        fail_fast_error_types=("policy_violation",),
        repair_step_id="repair",
    )
    step = _step(retry_policy=retry_policy)

    retry = _MACHINE.next_transition(
        step,
        _state(HarnessStepStatus.RUNNING, attempts=1),
        _observations(
            worker_result=StepWorkerObservation("failed", error="transient")
        ),
        _budget(max_retries_per_step=1),
    )
    exhausted = _MACHINE.next_transition(
        step,
        _state(HarnessStepStatus.RUNNING, attempts=2),
        _observations(
            worker_result=StepWorkerObservation("failed", error="still failing"),
            attempt=2,
        ),
        _budget(max_retries_per_step=1),
    )
    fail_fast = _MACHINE.next_transition(
        step,
        _state(HarnessStepStatus.RUNNING, attempts=1),
        _observations(
            worker_result=StepWorkerObservation(
                "failed",
                error="denied",
                error_type="policy_violation",
            )
        ),
        _budget(max_retries_per_step=4),
    )

    assert retry is not None
    assert retry.transition_type is StepLifecycleTransitionType.RETRY_STEP
    assert exhausted is not None
    assert exhausted.transition_type is StepLifecycleTransitionType.ROUTE_TO_REPAIR
    assert fail_fast is not None
    assert fail_fast.transition_type is StepLifecycleTransitionType.ROUTE_TO_REPAIR


def test_verification_requires_deterministic_gate_evidence() -> None:
    untrusted_worker_verdict = StepWorkerObservation(
        "succeeded",
        candidate_observations={
            "quality_verdict": {"passed": True, "score": 1.0},
            "verdict": "pass",
        },
    )
    pending = _MACHINE.next_transition(
        _step(),
        _state(HarnessStepStatus.VERIFYING),
        _observations(worker_result=untrusted_worker_verdict),
        _budget(),
    )
    accepted = _MACHINE.next_transition(
        _step(),
        _state(HarnessStepStatus.VERIFYING),
        _observations(
            worker_result=untrusted_worker_verdict,
            gate_results=(StepGateObservation("schema@1", True),),
            quality_verdict=StepQualityObservation(True, score=1.0),
        ),
        _budget(),
    )

    assert pending is not None
    assert pending.transition_type is StepLifecycleTransitionType.VERIFY_STEP
    assert accepted is not None
    assert accepted.transition_type is StepLifecycleTransitionType.COMPLETE_STEP


def test_worker_control_suggestions_are_observational_only() -> None:
    first_suggestions = {
        "route": "publish",
        "winner": "worker-selected",
        "loop": "continue",
        "verdict": "pass",
        "compensation": "skip",
        "approval_granted": True,
        "memory_write": True,
        "publication": "approved",
    }
    second_suggestions = {
        "route": "repair",
        "winner": "another-worker",
        "loop": "exit",
        "verdict": "fail",
        "compensation": "run",
        "approval_granted": False,
        "memory_write": False,
        "publication": "rejected",
    }
    step = _step(metadata={"approval_required": True})
    state = _state(HarnessStepStatus.RUNNING)

    first = _MACHINE.next_transition(
        step,
        state,
        _observations(
            worker_result=StepWorkerObservation(
                "succeeded",
                candidate_observations=first_suggestions,
            )
        ),
        _budget(),
    )
    second = _MACHINE.next_transition(
        step,
        state,
        _observations(
            worker_result=StepWorkerObservation(
                "succeeded",
                candidate_observations=second_suggestions,
            )
        ),
        _budget(),
    )

    assert first == second
    assert first is not None
    assert first.transition_type is StepLifecycleTransitionType.WAIT_FOR_APPROVAL
    assert first.reason_code == "harness_approval_required"


def test_worker_waiting_status_cannot_grant_approval_without_harness_policy() -> None:
    transition = _MACHINE.next_transition(
        _step(),
        _state(HarnessStepStatus.RUNNING),
        _observations(
            worker_result=StepWorkerObservation(
                "waiting_approval",
                candidate_observations={"approval_granted": True},
            )
        ),
        _budget(),
    )

    assert transition is not None
    assert transition.transition_type is StepLifecycleTransitionType.HALT_STEP
    assert transition.reason_code == "worker_approval_request_untrusted"
    assert transition.reason == "worker requested approval without Harness policy"


def test_gate_permutations_and_repeated_evaluation_are_deterministic() -> None:
    schema = StepGateObservation(
        "schema",
        False,
        reason="missing title",
        gate_reference="schema@1",
        details={"observed_at": "2026-07-30T00:00:00Z", "fields": ["title"]},
    )
    budget = StepGateObservation(
        "budget",
        True,
        gate_reference="budget@1",
        details={"observed_at": "2026-07-30T00:00:00Z"},
    )
    worker_a = StepWorkerObservation(
        "succeeded",
        candidate_observations={"b": 2, "a": 1},
    )
    worker_b = StepWorkerObservation(
        "succeeded",
        candidate_observations={"a": 1, "b": 2},
    )
    state = _state(HarnessStepStatus.VERIFYING)
    step = _step()
    lifecycle_budget = _budget(max_replans=2)

    first = _MACHINE.next_transition(
        step,
        state,
        _observations(
            worker_result=worker_a,
            gate_results=(schema, budget),
        ),
        lifecycle_budget,
    )
    second = _MACHINE.next_transition(
        step,
        state,
        _observations(
            worker_result=worker_b,
            gate_results=(budget, schema),
        ),
        lifecycle_budget,
    )

    assert first == second
    assert first is not None
    expected_serialization = stable_json_dumps(first.to_dict())
    for _ in range(20):
        repeated = _MACHINE.next_transition(
            step,
            state,
            _observations(
                worker_result=worker_b,
                gate_results=(budget, schema),
            ),
            lifecycle_budget,
        )
        assert repeated == first
        assert repeated is not None
        assert stable_json_dumps(repeated.to_dict()) == expected_serialization


def test_observations_budget_and_transition_are_deeply_immutable() -> None:
    worker = StepWorkerObservation(
        "failed",
        candidate_observations={"nested": {"items": ["a", "b"]}},
    )
    gate = StepGateObservation("schema", False, details={"missing": ["title"]})
    observations = _observations(
        worker_result=worker,
        gate_results=(gate,),
    )
    budget = _budget()
    transition = _MACHINE.next_transition(
        _step(),
        _state(HarnessStepStatus.VERIFYING),
        observations,
        budget,
    )

    with pytest.raises(FrozenInstanceError):
        observations.approval_granted = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        budget.turns_used = 1  # type: ignore[misc]
    with pytest.raises(TypeError):
        worker.candidate_observations["nested"] = {}  # type: ignore[index]
    nested = worker.candidate_observations["nested"]
    assert isinstance(nested, Mapping)
    with pytest.raises(TypeError):
        nested["items"] = ()  # type: ignore[index]
    assert transition is not None
    with pytest.raises(TypeError):
        transition.payload["new"] = True  # type: ignore[index]


def test_state_machine_performs_no_io_clock_random_or_mutable_global_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = Path(step_lifecycle_module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    forbidden_imports = {
        "http",
        "os",
        "random",
        "requests",
        "secrets",
        "socket",
        "subprocess",
        "time",
        "urllib",
        "uuid",
    }
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert imported_roots.isdisjoint(forbidden_imports)
    mutable_constants = {
        name
        for name, value in vars(step_lifecycle_module).items()
        if name.isupper() and isinstance(value, dict | list | set)
    }
    assert not mutable_constants

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise AssertionError("pure state machine touched an external runtime source")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(time, "time", forbidden)
    monkeypatch.setattr(random, "random", forbidden)
    monkeypatch.setattr(random, "choice", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(uuid, "uuid4", forbidden)

    transition = _MACHINE.next_transition(
        _step(),
        _state(HarnessStepStatus.PENDING),
        _observations(attempt=0),
        _budget(),
    )

    assert transition is not None
    assert transition.transition_type is StepLifecycleTransitionType.PLAN_STEP
    assert _MACHINE.version == HARNESS_STEP_LIFECYCLE_VERSION
    with pytest.raises(AttributeError):
        _MACHINE.mutable_state = True  # type: ignore[attr-defined]


def test_invalid_or_ambiguous_inputs_fail_closed() -> None:
    with pytest.raises(HarnessValidationError, match="another Step"):
        _MACHINE.next_transition(
            _step(),
            _state(HarnessStepStatus.PENDING, step_id="other"),
            _observations(attempt=0),
            _budget(),
        )

    with pytest.raises(HarnessValidationError, match="unique exact identities"):
        _observations(
            gate_results=(
                StepGateObservation("schema", True, gate_reference="schema@1"),
                StepGateObservation("schema", False, gate_reference="schema@1"),
            )
        )

    with pytest.raises(HarnessValidationError, match="canonical JSON"):
        StepWorkerObservation(
            "succeeded",
            candidate_observations={"callable": lambda: None},
        )

    with pytest.raises(HarnessValidationError, match="positive integer"):
        _budget(max_turns=0)

    with pytest.raises(HarnessValidationError, match="requires target_step_id"):
        StepLifecycleTransition(
            StepLifecycleTransitionType.ROUTE_TO_REPAIR,
            "draft",
            "repair_required",
        )


def _graph_identity(
    *,
    node_id: str = "draft-node",
    activation_ordinal: int = 1,
) -> HarnessNodeInstanceIdentity:
    return HarnessNodeInstanceIdentity(
        run_id="run-graph",
        graph_checksum=f"sha256:{'a' * 64}",
        node_id=node_id,
        activation_ordinal=activation_ordinal,
    )


def _accepted_evidence(
    node_instance_id: str,
    kind: HarnessEvidenceKind,
    *,
    attempt: int,
    event_sequence: int,
    marker: str,
) -> HarnessAttemptEvidenceReference:
    return HarnessAttemptEvidenceReference(
        evidence_ref=f"sha256:{marker * 64}",
        kind=kind,
        node_instance_id=node_instance_id,
        attempt=attempt,
        event_sequence=event_sequence,
    )


def _graph_node(
    *,
    identity: HarnessNodeInstanceIdentity | None = None,
    step_status: HarnessStepStatus = HarnessStepStatus.PENDING,
    node_status: HarnessNodeInstanceStatus | None = None,
    attempt: int = 0,
    last_event_sequence: int = 1,
    evidence_refs: tuple[HarnessAttemptEvidenceReference, ...] = (),
    step_id: str = "draft",
) -> HarnessNodeInstanceState:
    resolved_identity = identity or _graph_identity()
    resolved_node_status = node_status or (
        {
            HarnessStepStatus.PENDING: HarnessNodeInstanceStatus.READY,
            HarnessStepStatus.WAITING_APPROVAL: HarnessNodeInstanceStatus.WAITING,
            HarnessStepStatus.SUCCEEDED: HarnessNodeInstanceStatus.SUCCEEDED,
            HarnessStepStatus.FAILED: HarnessNodeInstanceStatus.FAILED,
            HarnessStepStatus.HALTED: HarnessNodeInstanceStatus.HALTED,
            HarnessStepStatus.SKIPPED: HarnessNodeInstanceStatus.SKIPPED,
        }.get(step_status, HarnessNodeInstanceStatus.RUNNING)
    )
    return HarnessNodeInstanceState(
        identity=resolved_identity,
        node_kind=HarnessGraphNodeKind.EXECUTABLE,
        status=resolved_node_status,
        step_id=step_id,
        step_ref=HarnessContractReference(
            HarnessContractKind.STEP,
            step_id,
            "1",
        ),
        step_status=step_status,
        attempt=attempt,
        evidence_refs=evidence_refs,
        activation_sequence=1,
        last_event_sequence=last_event_sequence,
    )


def _bound_gate(
    evidence: HarnessAttemptEvidenceReference,
    *,
    gate_name: str = "schema",
    gate_reference: str = "schema@1",
) -> StepGateObservation:
    return StepGateObservation(
        gate_name,
        True,
        gate_reference=gate_reference,
        input_ref=f"sha256:{'d' * 64}",
        result_ref=evidence.evidence_ref,
        gate_reason_code="schema_passed",
        accepted_evidence=evidence,
    )


def _step(
    *,
    retry_policy: HarnessRetryPolicy | None = None,
    metadata: dict[str, Any] | None = None,
    quality_gate: str | None = None,
) -> HarnessStepSpec:
    return HarnessStepSpec(
        "draft",
        "llm",
        retry_policy=retry_policy or HarnessRetryPolicy(),
        quality_gate=quality_gate,
        metadata={} if metadata is None else metadata,
    )


def _state(
    status: HarnessStepStatus,
    *,
    attempts: int | None = None,
    replans: int = 0,
    error: str | None = None,
    step_id: str = "draft",
) -> StepLifecycleState:
    resolved_attempts = (
        0
        if attempts is None and status is HarnessStepStatus.PENDING
        else 1
        if attempts is None
        else attempts
    )
    node = _graph_node(
        step_id=step_id,
        step_status=status,
        attempt=resolved_attempts,
        last_event_sequence=1,
        evidence_refs=(
            ()
            if resolved_attempts == 0
            else (
                _accepted_evidence(
                    _graph_identity().instance_id,
                    HarnessEvidenceKind.ACTIVITY_RESULT,
                    attempt=resolved_attempts,
                    event_sequence=1,
                    marker="a",
                ),
                _accepted_evidence(
                    _graph_identity().instance_id,
                    HarnessEvidenceKind.GATE_RESULT,
                    attempt=resolved_attempts,
                    event_sequence=1,
                    marker="b",
                ),
                _accepted_evidence(
                    _graph_identity().instance_id,
                    HarnessEvidenceKind.APPROVAL,
                    attempt=resolved_attempts,
                    event_sequence=1,
                    marker="c",
                ),
            )
        ),
    )
    lifecycle = StepLifecycleState.from_node_instance(node)
    if step_id == lifecycle.step_id:
        return lifecycle
    return StepLifecycleState(
        step_id=step_id,
        status=status,
        attempts=resolved_attempts,
        replans=replans,
        error=error,
        binding_mode=StepLifecycleBindingMode.GRAPH_BOUND,
        step_ref=HarnessContractReference(HarnessContractKind.STEP, step_id, "1"),
        node_instance_id=lifecycle.node_instance_id,
        last_event_sequence=lifecycle.last_event_sequence,
        evidence_refs=lifecycle.evidence_refs,
    )


def _observations(
    *,
    worker_result: StepWorkerObservation | None = None,
    gate_results: tuple[StepGateObservation, ...] = (),
    quality_verdict: StepQualityObservation | None = None,
    approval_granted: bool = False,
    approval_evidence: HarnessAttemptEvidenceReference | None = None,
    binding_mode: StepLifecycleBindingMode = StepLifecycleBindingMode.GRAPH_BOUND,
    node_instance_id: str | None = None,
    attempt: int | None = None,
    last_event_sequence: int | None = None,
) -> StepLifecycleObservations:
    """Build test observations with the canonical Graph node identity."""

    identity = _graph_identity().instance_id
    resolved_node = identity if node_instance_id is None else node_instance_id
    resolved_attempt = 1 if attempt is None else attempt
    resolved_sequence = 1 if last_event_sequence is None else last_event_sequence
    worker_evidence = _accepted_evidence(
        resolved_node,
        HarnessEvidenceKind.ACTIVITY_RESULT,
        attempt=resolved_attempt,
        event_sequence=resolved_sequence,
        marker="a",
    )
    if worker_result is not None and worker_result.accepted_evidence is None:
        worker_result = StepWorkerObservation(
            status=worker_result.status,
            error=worker_result.error,
            error_type=worker_result.error_type,
            candidate_observations=worker_result.candidate_observations,
            accepted_evidence=worker_evidence,
            cumulative_budget_fact=worker_result.cumulative_budget_fact,
        )
    resolved_gates: list[StepGateObservation] = []
    for index, gate in enumerate(gate_results):
        if gate.accepted_evidence is not None:
            resolved_gates.append(gate)
            continue
        gate_name = gate.gate_name.split("@", 1)[0]
        gate_reference = gate.gate_reference or f"{gate_name}@1"
        gate_evidence = _accepted_evidence(
            resolved_node,
            HarnessEvidenceKind.GATE_RESULT,
            attempt=resolved_attempt,
            event_sequence=resolved_sequence,
            marker="b",
        )
        resolved_gates.append(
            StepGateObservation(
                gate_name=gate_name,
                passed=gate.passed,
                reason=gate.reason,
                details=gate.details,
                gate_reference=gate_reference,
                input_ref=f"sha256:{'d' * 64}",
                result_ref=gate_evidence.evidence_ref,
                gate_reason_code=gate.gate_reason_code
                or ("gate_passed" if gate.passed else "gate_failed"),
                accepted_evidence=gate_evidence,
            )
        )
    if quality_verdict is not None and quality_verdict.accepted_evidence is None:
        quality_verdict = StepQualityObservation(
            passed=quality_verdict.passed,
            score=quality_verdict.score,
            issues=quality_verdict.issues,
            repair_hints=quality_verdict.repair_hints,
            metadata=quality_verdict.metadata,
            accepted_evidence=_accepted_evidence(
                resolved_node,
                HarnessEvidenceKind.GATE_RESULT,
                attempt=resolved_attempt,
                event_sequence=resolved_sequence,
                marker="b",
            ),
        )
    if approval_granted and approval_evidence is None:
        approval_evidence = _accepted_evidence(
            resolved_node,
            HarnessEvidenceKind.APPROVAL,
            attempt=resolved_attempt,
            event_sequence=resolved_sequence,
            marker="c",
        )
    return StepLifecycleObservations(
        worker_result=worker_result,
        gate_results=tuple(resolved_gates),
        quality_verdict=quality_verdict,
        approval_granted=approval_granted,
        approval_evidence=approval_evidence,
        binding_mode=binding_mode,
        node_instance_id=resolved_node,
        attempt=resolved_attempt,
        last_event_sequence=resolved_sequence,
    )


def _budget(
    *,
    max_turns: int = 20,
    turns_used: int = 0,
    max_replans: int = 2,
    replans_used: int = 0,
    max_retries_per_step: int = 2,
    max_worker_calls: int = 10,
    worker_calls_used: int = 0,
) -> StepLifecycleBudget:
    return StepLifecycleBudget(
        max_turns=max_turns,
        turns_used=turns_used,
        max_replans=max_replans,
        replans_used=replans_used,
        max_retries_per_step=max_retries_per_step,
        max_worker_calls=max_worker_calls,
        worker_calls_used=worker_calls_used,
    )
