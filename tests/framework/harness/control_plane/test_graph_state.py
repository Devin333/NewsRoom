from __future__ import annotations

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_state import (
    HarnessActiveActivityState,
    HarnessAttemptEvidenceReference,
    HarnessBudgetCounterState,
    HarnessCompensationEntry,
    HarnessEvidenceKind,
    HarnessGraphBudgetState,
    HarnessGraphReference,
    HarnessGraphState,
    HarnessJoinState,
    HarnessLegacyStatusProjection,
    HarnessLoopCounterState,
    HarnessLoopIteration,
    HarnessNodeInstanceIdentity,
    HarnessNodeInstanceState,
    HarnessWaitRegistration,
    RunLifecycle,
    RunOutcome,
    project_public_legacy_status,
)
from framework.harness.control_plane.state import HarnessRunStatus
from framework.harness.workflow.canonical import canonical_checksum
from framework.harness.workflow.graph import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.workflow.versioning import (
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_COMPILER_VERSION,
    NORMALIZED_HARNESS_GRAPH_SCHEMA,
)


def test_node_instance_identity_is_deterministic_and_scope_sensitive() -> None:
    first = _identity(
        "analyze",
        ordinal=7,
        branch_path=("analysis", "structure"),
        iteration_vector=(HarnessLoopIteration("repair", 1),),
    )
    repeated = _identity(
        "analyze",
        ordinal=7,
        branch_path=("analysis", "structure"),
        iteration_vector=(HarnessLoopIteration("repair", 1),),
    )

    assert first == repeated
    assert first.instance_id == repeated.instance_id
    assert HarnessNodeInstanceIdentity.from_dict(first.to_dict()) == first
    assert (
        _identity(
            "analyze",
            ordinal=7,
            branch_path=("analysis", "contribution"),
            iteration_vector=(HarnessLoopIteration("repair", 1),),
        ).instance_id
        != first.instance_id
    )
    assert (
        _identity(
            "analyze",
            ordinal=7,
            branch_path=("analysis", "structure"),
            iteration_vector=(HarnessLoopIteration("repair", 2),),
        ).instance_id
        != first.instance_id
    )
    assert (
        _identity(
            "analyze",
            ordinal=8,
            branch_path=("analysis", "structure"),
            iteration_vector=(HarnessLoopIteration("repair", 1),),
        ).instance_id
        != first.instance_id
    )


def test_nested_branch_path_may_repeat_local_branch_names() -> None:
    identity = _identity(
        "analyze",
        ordinal=9,
        branch_path=("left", "left"),
    )

    assert identity.branch_path == ("left", "left")
    assert HarnessNodeInstanceIdentity.from_dict(identity.to_dict()) == identity


def test_retry_stays_in_one_instance_but_next_loop_iteration_does_not() -> None:
    first_iteration = _identity(
        "retrieve",
        ordinal=2,
        iteration_vector=(HarnessLoopIteration("coverage", 0),),
    )
    retry = _executable_node(first_iteration, "running", attempt=2)
    original_attempt = _executable_node(first_iteration, "running", attempt=1)
    next_iteration = _identity(
        "retrieve",
        ordinal=3,
        iteration_vector=(HarnessLoopIteration("coverage", 1),),
    )

    assert retry.instance_id == original_attempt.instance_id
    assert retry.attempt == original_attempt.attempt + 1
    assert next_iteration.instance_id != first_iteration.instance_id


def test_node_state_deep_freezes_future_decision_fields() -> None:
    output_refs = {"candidate": {"ref": _sha("candidate")}}
    metadata = {"routing": {"eligible": ["next"]}}
    node = _executable_node(
        _identity("analyze", ordinal=1),
        "ready",
        attempt=0,
        output_refs=output_refs,
        metadata=metadata,
    )
    output_refs["candidate"]["ref"] = "changed"
    metadata["routing"]["eligible"].append("other")

    assert node.to_dict()["output_refs"] == {"candidate": {"ref": _sha("candidate")}}
    assert node.to_dict()["metadata"] == {"routing": {"eligible": ["next"]}}
    with pytest.raises(TypeError):
        node.output_refs["new"] = "forbidden"


def test_graph_state_round_trips_with_stable_parallel_projections_and_checksum() -> (
    None
):
    first = _full_graph_state(reverse_inputs=False)
    permuted = _full_graph_state(reverse_inputs=True)
    restored = HarnessGraphState.from_dict(first.to_dict())

    assert restored == first
    assert first.to_dict() == restored.to_dict()
    assert first.projection_checksum == permuted.projection_checksum
    assert first.to_dict() == permuted.to_dict()
    assert len(first.running_node_ids) == 2
    assert len(first.waiting_node_ids) == 1
    assert len(first.terminal_node_ids) == 2
    assert first.ready_node_ids == ()
    assert first.lifecycle is RunLifecycle.RUNNING
    assert set(first.running_node_ids).isdisjoint(first.waiting_node_ids)
    assert set(first.running_node_ids).isdisjoint(first.terminal_node_ids)


def test_projection_checksum_rejects_tampering() -> None:
    state = _full_graph_state()
    payload = state.to_dict()
    payload["last_event_sequence"] += 1

    with pytest.raises(HarnessValidationError) as captured:
        HarnessGraphState.from_dict(payload)

    assert captured.value.code == "graph_state_checksum_mismatch"


def test_projection_checksum_covers_every_future_scheduling_field_group() -> None:
    state = _full_graph_state()
    projection = state.checksum_projection()
    covered_fields = {
        "schema_version",
        "runtime_version",
        "run_id",
        "graph_ref",
        "lifecycle",
        "outcome",
        "node_instances",
        "active_activities",
        "join_states",
        "loop_counters",
        "wait_registrations",
        "compensation_stack",
        "budgets",
        "last_event_sequence",
        "terminal_reason_code",
        "terminal_evidence_ref",
        "metadata",
    }

    assert set(projection) == covered_fields
    for field_name in sorted(covered_fields):
        changed = dict(projection)
        changed[field_name] = {"changed": field_name}
        assert canonical_checksum(changed) != state.projection_checksum


def test_initial_graph_state_pins_graph_budget_and_empty_created_projection() -> None:
    budgets = HarnessGraphBudgetState(
        (HarnessBudgetCounterState("node_activations", 10),)
    )
    state = HarnessGraphState.initial(
        run_id="run-1",
        graph_ref=_graph_ref(),
        budgets=budgets,
        metadata={"input_projection_ref": _sha("inputs")},
    )

    assert state.lifecycle is RunLifecycle.CREATED
    assert state.outcome is RunOutcome.NONE
    assert state.node_instances == ()
    assert state.last_event_sequence == 0
    assert state.budgets is budgets
    assert state.projection_checksum == canonical_checksum(state.checksum_projection())


def test_node_identity_payload_rejects_tampered_instance_id() -> None:
    payload = _identity("collect", ordinal=0).to_dict()
    payload["instance_id"] = "hni_invalid"

    with pytest.raises(HarnessValidationError) as captured:
        HarnessNodeInstanceIdentity.from_dict(payload)

    assert captured.value.code == "node_instance_identity_mismatch"


def test_gate_or_activity_evidence_from_another_instance_or_attempt_is_rejected() -> (
    None
):
    identity = _identity("analyze", ordinal=1)
    other = _identity("analyze", ordinal=2)

    with pytest.raises(HarnessValidationError) as cross_node:
        _executable_node(
            identity,
            "running",
            attempt=1,
            evidence_refs=(
                HarnessAttemptEvidenceReference(
                    _sha("gate"),
                    HarnessEvidenceKind.GATE_RESULT,
                    other.instance_id,
                    1,
                    3,
                ),
            ),
        )
    with pytest.raises(HarnessValidationError) as cross_attempt:
        _executable_node(
            identity,
            "running",
            attempt=1,
            evidence_refs=(
                HarnessAttemptEvidenceReference(
                    _sha("gate"),
                    HarnessEvidenceKind.GATE_RESULT,
                    identity.instance_id,
                    2,
                    3,
                ),
            ),
        )

    assert cross_node.value.code == "cross_node_evidence_rejected"
    assert cross_attempt.value.code == "cross_attempt_evidence_rejected"


def test_node_evidence_cannot_advance_past_node_projection_sequence() -> None:
    identity = _identity("analyze", ordinal=1)

    with pytest.raises(HarnessValidationError) as captured:
        _executable_node(
            identity,
            "running",
            attempt=1,
            evidence_refs=(
                HarnessAttemptEvidenceReference(
                    _sha("future-gate"),
                    HarnessEvidenceKind.GATE_RESULT,
                    identity.instance_id,
                    1,
                    5,
                ),
            ),
            last_event_sequence=4,
        )

    assert captured.value.code == "graph_state_sequence_regression"


def test_active_activity_must_match_running_node_and_current_attempt() -> None:
    running = _executable_node(
        _identity("analyze", ordinal=0),
        "running",
        attempt=1,
    )
    waiting = _executable_node(
        _identity("approval", ordinal=1),
        "waiting",
        attempt=1,
        step_status="waiting_approval",
        activation_sequence=2,
    )

    with pytest.raises(HarnessValidationError) as cross_attempt:
        _minimal_state(
            nodes=(running,),
            activities=(_activity(running.instance_id, attempt=2),),
        )
    with pytest.raises(HarnessValidationError) as wrong_status:
        _minimal_state(
            nodes=(waiting,),
            activities=(_activity(waiting.instance_id, attempt=1),),
        )

    assert cross_attempt.value.code == "cross_attempt_activity_rejected"
    assert wrong_status.value.code == "activity_node_state_mismatch"


def test_waiting_lifecycle_requires_only_unresolved_waiting_work() -> None:
    waiting = _wait_node(_identity("approval", ordinal=0), sequence=1)
    registration = _wait_registration(waiting.instance_id, sequence=1)
    state = _minimal_state(
        nodes=(waiting,),
        waits=(registration,),
        lifecycle="waiting",
    )

    assert state.lifecycle is RunLifecycle.WAITING
    with pytest.raises(HarnessValidationError) as runnable:
        _minimal_state(
            nodes=(
                waiting,
                _executable_node(_identity("next", ordinal=1), "ready", attempt=0),
            ),
            waits=(registration,),
            lifecycle="waiting",
        )
    with pytest.raises(HarnessValidationError) as no_wait:
        _minimal_state(nodes=(), waits=(), lifecycle="waiting")

    assert runnable.value.code == "invalid_waiting_run_projection"
    assert no_wait.value.code == "invalid_waiting_run_projection"


def test_join_loop_compensation_and_budget_invariants_fail_closed() -> None:
    with pytest.raises(HarnessValidationError) as incomplete_join:
        HarnessJoinState(
            "join-instance",
            "fork-instance",
            "all",
            "satisfied",
            ("left", "right"),
            {"left": "node-left"},
            {"left": _sha("left-terminal")},
            last_event_sequence=3,
        )
    with pytest.raises(HarnessValidationError) as missing_winner:
        HarnessJoinState(
            "join-instance",
            "fork-instance",
            "any",
            "satisfied",
            ("left", "right"),
            {"left": "node-left"},
            {"left": _sha("left-terminal")},
            last_event_sequence=3,
        )
    with pytest.raises(HarnessValidationError) as loop_overflow:
        HarnessLoopCounterState("loop", (), (), 4, 3)
    with pytest.raises(HarnessValidationError) as budget_overflow:
        HarnessBudgetCounterState("worker_calls", limit=2, used=2, reserved=1)

    assert incomplete_join.value.code == "incomplete_parallel_all_join"
    assert missing_winner.value.code == "parallel_any_winner_missing"
    assert loop_overflow.value.code == "loop_iteration_bound_exceeded"
    assert budget_overflow.value.code == "graph_budget_exceeded"


def test_join_completion_rejects_unknown_or_nonterminal_node_evidence() -> None:
    running = _executable_node(
        _identity("branch", ordinal=0, branch_path=("branch",)),
        "running",
        attempt=1,
    )
    fork = _control_node(
        _identity("fork", ordinal=1),
        node_kind="fork_all",
        status="succeeded",
        sequence=1,
    )
    join_node = _control_node(
        _identity("join", ordinal=2),
        node_kind="join_all",
        status="running",
        sequence=2,
    )
    for instance_id, expected_code in (
        ("missing-instance", "cross_node_join_evidence_rejected"),
        (running.instance_id, "nonterminal_join_evidence_rejected"),
    ):
        join = HarnessJoinState(
            join_node.instance_id,
            fork.instance_id,
            "all",
            "open",
            ("branch",),
            {"branch": instance_id},
            {"branch": _sha("terminal")},
            last_event_sequence=2,
        )

        with pytest.raises(HarnessValidationError) as captured:
            _minimal_state(nodes=(running, fork, join_node), joins=(join,))

        assert captured.value.code == expected_code


def test_completed_run_rejects_active_or_nonterminal_projection() -> None:
    running = _executable_node(
        _identity("active", ordinal=0),
        "running",
        attempt=1,
        activation_sequence=1,
        last_event_sequence=2,
    )

    with pytest.raises(HarnessValidationError) as captured:
        _minimal_state(
            nodes=(running,),
            activities=(_activity(running.instance_id, attempt=1),),
            lifecycle="completed",
            outcome="succeeded",
        )

    assert captured.value.code == "invalid_completed_run_projection"


@pytest.mark.parametrize(
    ("node_status", "step_status", "attempt"),
    (
        ("ready", "succeeded", 0),
        ("running", "pending", 1),
        ("waiting", "running", 1),
        ("succeeded", "running", 1),
        ("failed", "verifying", 1),
        ("halted", "planning", 1),
        ("compensated", "failed", 1),
    ),
)
def test_node_status_rejects_incompatible_step_lifecycle_status(
    node_status: str,
    step_status: str,
    attempt: int,
) -> None:
    with pytest.raises(HarnessValidationError) as captured:
        _executable_node(
            _identity("step", ordinal=0),
            node_status,
            attempt=attempt,
            step_status=step_status,
        )

    assert captured.value.code == "node_step_status_mismatch"


@pytest.mark.parametrize(
    "kind",
    (
        HarnessEvidenceKind.ACTIVITY_RESULT,
        HarnessEvidenceKind.GATE_RESULT,
        HarnessEvidenceKind.SIDE_EFFECT_OUTCOME,
    ),
)
def test_control_node_rejects_executable_attempt_evidence(
    kind: HarnessEvidenceKind,
) -> None:
    identity = _identity("choice", ordinal=0)

    with pytest.raises(HarnessValidationError) as captured:
        HarnessNodeInstanceState(
            identity=identity,
            node_kind="choice",
            status="running",
            evidence_refs=(
                HarnessAttemptEvidenceReference(
                    _sha(kind.value),
                    kind,
                    identity.instance_id,
                    0,
                    1,
                ),
            ),
            activation_sequence=1,
            last_event_sequence=1,
        )

    assert captured.value.code == "invalid_control_node_evidence"


@pytest.mark.parametrize(
    "reference_case",
    ("attempt_evidence", "effect_outcome", "compensation_outcome", "legacy"),
)
def test_durable_evidence_fields_require_canonical_sha256_references(
    reference_case: str,
) -> None:
    with pytest.raises(HarnessValidationError) as captured:
        if reference_case == "attempt_evidence":
            HarnessAttemptEvidenceReference(
                "plain-text",
                "gate_result",
                "node",
                1,
                1,
            )
        elif reference_case == "effect_outcome":
            HarnessCompensationEntry(
                "entry",
                "origin",
                "plain-text",
                1,
                _ref(HarnessContractKind.COMPENSATION, "undo", "1"),
                _ref(HarnessContractKind.ACTIVITY, "undo.activity", "1"),
                "entry:idempotency",
                1,
            )
        elif reference_case == "compensation_outcome":
            HarnessCompensationEntry(
                "entry",
                "origin",
                _sha("effect"),
                1,
                _ref(HarnessContractKind.COMPENSATION, "undo", "1"),
                _ref(HarnessContractKind.ACTIVITY, "undo.activity", "1"),
                "entry:idempotency",
                1,
                status="succeeded",
                compensation_node_instance_id="compensation-node",
                outcome_ref="plain-text",
                last_event_sequence=2,
            )
        else:
            HarnessLegacyStatusProjection(
                "halted",
                indeterminate_evidence_ref="plain-text",
            )

    assert captured.value.code == "invalid_graph_checksum_reference"


def test_activity_and_wait_bindings_reject_wrong_node_kinds() -> None:
    control = _control_node(
        _identity("choice", ordinal=0),
        node_kind="choice",
        status="running",
        sequence=1,
    )
    executable_waiting = _executable_node(
        _identity("approval-step", ordinal=1),
        "waiting",
        attempt=1,
        activation_sequence=1,
        last_event_sequence=1,
    )

    with pytest.raises(HarnessValidationError) as activity_error:
        _minimal_state(
            nodes=(control,),
            activities=(_activity(control.instance_id, attempt=1),),
        )
    with pytest.raises(HarnessValidationError) as wait_error:
        _minimal_state(
            nodes=(executable_waiting,),
            waits=(_wait_registration(executable_waiting.instance_id, sequence=1),),
        )

    assert activity_error.value.code == "activity_node_kind_mismatch"
    assert wait_error.value.code == "wait_node_kind_mismatch"


def test_active_activity_attempt_is_unique_and_sequence_bound_to_node() -> None:
    running = _executable_node(
        _identity("worker", ordinal=0),
        "running",
        attempt=1,
        activation_sequence=5,
        last_event_sequence=7,
    )

    with pytest.raises(HarnessValidationError) as early_dispatch:
        _minimal_state(
            nodes=(running,),
            activities=(
                _activity(
                    running.instance_id,
                    attempt=1,
                    dispatched_sequence=4,
                ),
            ),
        )
    with pytest.raises(HarnessValidationError) as duplicate_attempt:
        _minimal_state(
            nodes=(running,),
            activities=(
                _activity(
                    running.instance_id,
                    attempt=1,
                    activity_id="activity-a",
                    idempotency_key="key-a",
                    dispatched_sequence=6,
                ),
                _activity(
                    running.instance_id,
                    attempt=1,
                    activity_id="activity-b",
                    idempotency_key="key-b",
                    dispatched_sequence=6,
                ),
            ),
        )

    assert early_dispatch.value.code == "graph_state_sequence_regression"
    assert duplicate_attempt.value.code == "duplicate_active_activity_attempt"


def test_wait_state_requires_one_sequence_aligned_durable_registration() -> None:
    waiting = _wait_node(_identity("approval", ordinal=0), sequence=5)

    with pytest.raises(HarnessValidationError) as missing:
        _minimal_state(nodes=(waiting,))
    with pytest.raises(HarnessValidationError) as duplicate:
        _minimal_state(
            nodes=(waiting,),
            waits=(
                _wait_registration(
                    waiting.instance_id,
                    sequence=5,
                    wait_id="wait-a",
                ),
                _wait_registration(
                    waiting.instance_id,
                    sequence=5,
                    wait_id="wait-b",
                ),
            ),
        )
    with pytest.raises(HarnessValidationError) as early:
        _minimal_state(
            nodes=(waiting,),
            waits=(_wait_registration(waiting.instance_id, sequence=4),),
        )

    assert missing.value.code == "wait_registration_missing"
    assert duplicate.value.code == "duplicate_wait_node_registration"
    assert early.value.code == "graph_state_sequence_regression"


def test_parallel_any_winner_must_be_successful_and_branch_scoped() -> None:
    fork = _control_node(
        _identity("fork", ordinal=0),
        node_kind="fork_any",
        status="succeeded",
        sequence=1,
    )
    join_node = _control_node(
        _identity("join", ordinal=1),
        node_kind="join_any",
        status="succeeded",
        sequence=4,
    )
    failed = _executable_node(
        _identity("branch", ordinal=2, branch_path=("left",)),
        "failed",
        attempt=1,
        activation_sequence=2,
        last_event_sequence=3,
    )
    failed_winner = HarnessJoinState(
        join_node.instance_id,
        fork.instance_id,
        "any",
        "satisfied",
        ("left",),
        {"left": failed.instance_id},
        {"left": _sha("failed-terminal")},
        winner_branch_id="left",
        last_event_sequence=4,
    )

    with pytest.raises(HarnessValidationError) as captured:
        _minimal_state(nodes=(fork, join_node, failed), joins=(failed_winner,))

    assert captured.value.code == "parallel_any_winner_state_mismatch"


def test_join_rejects_mismatched_control_kind_and_branch_scope() -> None:
    fork = _control_node(
        _identity("fork", ordinal=0),
        node_kind="fork_all",
        status="succeeded",
        sequence=1,
    )
    wrong_join_node = _control_node(
        _identity("join", ordinal=1),
        node_kind="join_any",
        status="running",
        sequence=4,
    )
    terminal = _executable_node(
        _identity("branch", ordinal=2, branch_path=("right",)),
        "succeeded",
        attempt=1,
        activation_sequence=2,
        last_event_sequence=3,
    )
    join = HarnessJoinState(
        wrong_join_node.instance_id,
        fork.instance_id,
        "all",
        "open",
        ("left",),
        {"left": terminal.instance_id},
        {"left": _sha("terminal")},
        last_event_sequence=4,
    )

    with pytest.raises(HarnessValidationError) as wrong_kind:
        _minimal_state(nodes=(fork, wrong_join_node, terminal), joins=(join,))

    correct_join_node = _control_node(
        _identity("join-all", ordinal=3),
        node_kind="join_all",
        status="running",
        sequence=4,
    )
    scoped_join = HarnessJoinState(
        correct_join_node.instance_id,
        fork.instance_id,
        "all",
        "open",
        ("left",),
        {"left": terminal.instance_id},
        {"left": _sha("terminal")},
        last_event_sequence=4,
    )
    with pytest.raises(HarnessValidationError) as wrong_scope:
        _minimal_state(nodes=(fork, correct_join_node, terminal), joins=(scoped_join,))

    assert wrong_kind.value.code == "join_node_kind_mismatch"
    assert wrong_scope.value.code == "join_branch_scope_mismatch"


def test_compensation_requires_exact_origin_effect_and_executable_state() -> None:
    origin_identity = _identity("publish", ordinal=0)
    origin_without_effect = _executable_node(
        origin_identity,
        "succeeded",
        attempt=1,
        activation_sequence=1,
        last_event_sequence=2,
    )
    entry = HarnessCompensationEntry(
        "undo",
        origin_without_effect.instance_id,
        _sha("effect"),
        2,
        _ref(HarnessContractKind.COMPENSATION, "undo", "1"),
        _ref(HarnessContractKind.ACTIVITY, "undo.activity", "1"),
        "undo:run-1",
        1,
        last_event_sequence=2,
    )

    with pytest.raises(HarnessValidationError) as missing_effect:
        _minimal_state(nodes=(origin_without_effect,), compensations=(entry,))

    effect_ref = _sha("effect")
    origin = _executable_node(
        origin_identity,
        "succeeded",
        attempt=1,
        evidence_refs=(
            HarnessAttemptEvidenceReference(
                effect_ref,
                "side_effect_outcome",
                origin_identity.instance_id,
                1,
                2,
            ),
        ),
        activation_sequence=1,
        last_event_sequence=2,
    )
    compensation_control = _control_node(
        _identity("undo-control", ordinal=1),
        node_kind="choice",
        status="running",
        sequence=3,
    )
    running_entry = HarnessCompensationEntry(
        "undo-running",
        origin.instance_id,
        effect_ref,
        2,
        _ref(HarnessContractKind.COMPENSATION, "undo", "1"),
        _ref(HarnessContractKind.ACTIVITY, "undo.activity", "1"),
        "undo-running:run-1",
        1,
        status="running",
        compensation_node_instance_id=compensation_control.instance_id,
        last_event_sequence=3,
    )
    with pytest.raises(HarnessValidationError) as wrong_node_kind:
        _minimal_state(
            nodes=(origin, compensation_control),
            compensations=(running_entry,),
        )

    assert missing_effect.value.code == "compensation_effect_evidence_mismatch"
    assert wrong_node_kind.value.code == "compensation_node_kind_mismatch"


def test_ready_nodes_count_toward_max_active_nodes() -> None:
    ready = _executable_node(
        _identity("ready", ordinal=0),
        "ready",
        attempt=0,
    )
    budgets = HarnessGraphBudgetState(
        (
            HarnessBudgetCounterState("max_parallelism", 0),
            HarnessBudgetCounterState("max_active_nodes", 0),
        )
    )

    with pytest.raises(HarnessValidationError) as captured:
        _minimal_state(nodes=(ready,), budgets=budgets)

    assert captured.value.code == "graph_active_node_limit_exceeded"


def test_created_and_terminal_run_projections_fail_closed() -> None:
    running = _executable_node(
        _identity("active", ordinal=0),
        "running",
        attempt=1,
    )
    with pytest.raises(HarnessValidationError) as created:
        _minimal_state(nodes=(running,), lifecycle="created")
    with pytest.raises(HarnessValidationError) as halted_without_reason:
        _minimal_state(nodes=(), lifecycle="halted")
    with pytest.raises(HarnessValidationError) as indeterminate_without_evidence:
        _minimal_state(
            nodes=(),
            lifecycle="halted",
            outcome="indeterminate",
            terminal_reason_code="activity_outcome_unknown",
        )

    assert created.value.code == "invalid_created_run_projection"
    assert halted_without_reason.value.code == "terminal_reason_missing"
    assert indeterminate_without_evidence.value.code == "terminal_evidence_missing"


def test_two_parallel_executable_branches_remain_independent_and_stable() -> None:
    left = _executable_node(
        _identity("left-step", ordinal=0, branch_path=("left",)),
        "running",
        attempt=1,
        activation_sequence=1,
        last_event_sequence=2,
    )
    right = _executable_node(
        _identity("right-step", ordinal=1, branch_path=("right",)),
        "running",
        attempt=1,
        activation_sequence=1,
        last_event_sequence=2,
    )
    activities = (
        _activity(
            left.instance_id,
            attempt=1,
            activity_id="left-activity",
            idempotency_key="left-key",
        ),
        _activity(
            right.instance_id,
            attempt=1,
            activity_id="right-activity",
            idempotency_key="right-key",
        ),
    )
    budgets = HarnessGraphBudgetState(
        (
            HarnessBudgetCounterState("max_parallelism", 2),
            HarnessBudgetCounterState("max_active_nodes", 2),
        )
    )
    first = _minimal_state(
        nodes=(left, right),
        activities=activities,
        budgets=budgets,
    )
    permuted = _minimal_state(
        nodes=(right, left),
        activities=tuple(reversed(activities)),
        budgets=budgets,
    )

    assert first.running_node_ids == (left.instance_id, right.instance_id)
    assert first.running_node_ids == permuted.running_node_ids
    assert first.projection_checksum == permuted.projection_checksum
    assert left.instance_id != right.instance_id


def test_identity_and_graph_state_reject_cross_scope_or_duplicate_nodes() -> None:
    baseline = _identity("node", ordinal=0)
    variants = (
        HarnessNodeInstanceIdentity(
            "run-2",
            baseline.graph_checksum,
            "node",
            activation_ordinal=0,
        ),
        HarnessNodeInstanceIdentity(
            "run-1",
            _sha("other-graph"),
            "node",
            activation_ordinal=0,
        ),
        _identity("other-node", ordinal=0),
    )
    assert len({baseline.instance_id, *(item.instance_id for item in variants)}) == 4

    cross_run = _executable_node(variants[0], "ready", attempt=0)
    cross_graph = _executable_node(variants[1], "ready", attempt=0)
    duplicate_ordinal = _executable_node(variants[2], "ready", attempt=0)
    baseline_node = _executable_node(baseline, "ready", attempt=0)

    with pytest.raises(HarnessValidationError) as run_error:
        _minimal_state(nodes=(cross_run,))
    with pytest.raises(HarnessValidationError) as graph_error:
        _minimal_state(nodes=(cross_graph,))
    with pytest.raises(HarnessValidationError) as duplicate_instance:
        _minimal_state(nodes=(baseline_node, baseline_node))
    with pytest.raises(HarnessValidationError) as ordinal_error:
        _minimal_state(nodes=(baseline_node, duplicate_ordinal))

    assert run_error.value.code == "cross_run_node_instance_rejected"
    assert graph_error.value.code == "cross_graph_node_instance_rejected"
    assert duplicate_instance.value.code == "duplicate_graph_state_identity"
    assert ordinal_error.value.code == "duplicate_node_activation_ordinal"


def test_legacy_projection_rejects_schema_tampering_and_irrelevant_flags() -> None:
    with pytest.raises(HarnessValidationError) as schema_error:
        HarnessLegacyStatusProjection("running", source_schema="unknown/v1")
    with pytest.raises(HarnessValidationError) as resumable_error:
        HarnessLegacyStatusProjection("running", resumable_blocked=True)
    with pytest.raises(HarnessValidationError) as approval_error:
        project_public_legacy_status(
            "running",
            "none",
            waiting_for_approval=True,
        )

    payload = HarnessLegacyStatusProjection("succeeded").to_dict()
    payload["outcome"] = "failed"
    with pytest.raises(HarnessValidationError) as tampered:
        HarnessLegacyStatusProjection.from_dict(payload)

    assert schema_error.value.code == "unsupported_legacy_state_schema"
    assert resumable_error.value.code == "invalid_legacy_status_projection"
    assert approval_error.value.code == "invalid_legacy_status_projection"
    assert tampered.value.code == "legacy_status_projection_mismatch"


def test_projection_checksum_covers_nested_future_decision_leaves() -> None:
    state = _full_graph_state()
    projection = state.checksum_projection()
    mutations = (
        ("node attempt", projection["node_instances"][1], "attempt", 9),
        (
            "activity fencing",
            projection["active_activities"][0],
            "fencing_generation",
            9,
        ),
        (
            "loop count",
            projection["loop_counters"][0],
            "completed_iterations",
            2,
        ),
        (
            "compensation key",
            projection["compensation_stack"][0],
            "idempotency_key",
            "changed",
        ),
        (
            "budget usage",
            projection["budgets"]["counters"][0],
            "used",
            99,
        ),
    )

    for _label, target, field_name, replacement in mutations:
        original = target[field_name]
        target[field_name] = replacement
        assert canonical_checksum(projection) != state.projection_checksum
        target[field_name] = original


@pytest.mark.parametrize(
    ("status", "resumable", "lifecycle", "outcome"),
    (
        ("created", False, "created", "none"),
        ("running", False, "running", "none"),
        ("planning", False, "running", "none"),
        ("executing", False, "running", "none"),
        ("verifying", False, "running", "none"),
        ("replanning", False, "running", "none"),
        ("waiting_approval", False, "waiting", "none"),
        ("blocked", True, "waiting", "none"),
        ("blocked", False, "halted", "none"),
        ("succeeded", False, "completed", "succeeded"),
        ("failed", False, "completed", "failed"),
        ("cancelled", False, "completed", "cancelled"),
        ("halted", False, "halted", "none"),
    ),
)
def test_v1_status_reader_uses_fixed_lifecycle_outcome_mapping(
    status: str,
    resumable: bool,
    lifecycle: str,
    outcome: str,
) -> None:
    projection = HarnessLegacyStatusProjection(status, resumable_blocked=resumable)

    assert projection.lifecycle.value == lifecycle
    assert projection.outcome.value == outcome
    assert HarnessLegacyStatusProjection.from_dict(projection.to_dict()) == projection


def test_halted_indeterminate_requires_durable_evidence_and_projects_as_halted() -> (
    None
):
    projection = HarnessLegacyStatusProjection(
        "halted",
        indeterminate_evidence_ref=_sha("uncertain-termination"),
    )

    assert projection.lifecycle is RunLifecycle.HALTED
    assert projection.outcome is RunOutcome.INDETERMINATE
    assert (
        project_public_legacy_status(
            projection.lifecycle,
            projection.outcome,
        )
        is HarnessRunStatus.HALTED
    )
    with pytest.raises(HarnessValidationError) as invalid_evidence:
        HarnessLegacyStatusProjection(
            "failed",
            indeterminate_evidence_ref=_sha("not-halted"),
        )
    assert invalid_evidence.value.code == "invalid_legacy_status_projection"


@pytest.mark.parametrize(
    ("lifecycle", "outcome", "approval", "expected"),
    (
        ("created", "none", False, HarnessRunStatus.CREATED),
        ("running", "none", False, HarnessRunStatus.RUNNING),
        ("waiting", "none", False, HarnessRunStatus.BLOCKED),
        ("waiting", "none", True, HarnessRunStatus.WAITING_APPROVAL),
        ("completed", "succeeded", False, HarnessRunStatus.SUCCEEDED),
        ("completed", "compensated", False, HarnessRunStatus.SUCCEEDED),
        ("completed", "failed", False, HarnessRunStatus.FAILED),
        ("completed", "compensation_failed", False, HarnessRunStatus.FAILED),
        ("completed", "cancelled", False, HarnessRunStatus.CANCELLED),
        ("halted", "indeterminate", False, HarnessRunStatus.HALTED),
    ),
)
def test_v2_public_legacy_status_projection_is_bounded(
    lifecycle: str,
    outcome: str,
    approval: bool,
    expected: HarnessRunStatus,
) -> None:
    assert (
        project_public_legacy_status(
            lifecycle,
            outcome,
            waiting_for_approval=approval,
        )
        is expected
    )


def test_lifecycle_and_outcome_are_independent_but_compatible() -> None:
    with pytest.raises(HarnessValidationError) as running_terminal:
        _minimal_state(nodes=(), lifecycle="running", outcome="failed")
    with pytest.raises(HarnessValidationError) as completed_none:
        _minimal_state(nodes=(), lifecycle="completed", outcome="none")

    assert running_terminal.value.code == "invalid_run_lifecycle_outcome"
    assert completed_none.value.code == "invalid_run_lifecycle_outcome"


def _full_graph_state(*, reverse_inputs: bool = False) -> HarnessGraphState:
    fork_identity = _identity("analysis-fork", ordinal=0)
    running_identity = _identity(
        "analyze",
        ordinal=1,
        branch_path=("analysis", "right"),
    )
    terminal_identity = _identity(
        "publish",
        ordinal=2,
        branch_path=("analysis", "left"),
    )
    join_identity = _identity("analysis-join", ordinal=3)
    waiting_identity = _identity("approval", ordinal=4, branch_path=("editor",))
    evidence = HarnessAttemptEvidenceReference(
        _sha("worker-result"),
        HarnessEvidenceKind.ACTIVITY_RESULT,
        running_identity.instance_id,
        1,
        3,
    )
    running = _executable_node(
        running_identity,
        "running",
        attempt=1,
        evidence_refs=(evidence,),
        activation_sequence=1,
        last_event_sequence=4,
    )
    fork = _control_node(
        fork_identity,
        node_kind="fork_all",
        status="succeeded",
        sequence=1,
    )
    join_node = _control_node(
        join_identity,
        node_kind="join_all",
        status="running",
        sequence=6,
    )
    waiting = _wait_node(waiting_identity, sequence=5)
    effect_ref = _sha("publication-outcome")
    terminal = _executable_node(
        terminal_identity,
        "succeeded",
        attempt=1,
        step_status="succeeded",
        evidence_refs=(
            HarnessAttemptEvidenceReference(
                effect_ref,
                HarnessEvidenceKind.SIDE_EFFECT_OUTCOME,
                terminal_identity.instance_id,
                1,
                4,
            ),
        ),
        activation_sequence=3,
        last_event_sequence=4,
    )
    activity = _activity(running.instance_id, attempt=1)
    wait = _wait_registration(waiting.instance_id, sequence=5)
    join = HarnessJoinState(
        join_node.instance_id,
        fork.instance_id,
        "all",
        "open",
        ("right", "left"),
        {"left": terminal.instance_id},
        {"left": _sha("left-terminal")},
        last_event_sequence=6,
    )
    loop = HarnessLoopCounterState(
        "repair-loop",
        ("analysis",),
        (),
        1,
        3,
        "active",
        7,
    )
    compensation = HarnessCompensationEntry(
        "undo-publication",
        terminal.instance_id,
        effect_ref,
        4,
        _ref(HarnessContractKind.COMPENSATION, "publication.undo", "1"),
        _ref(HarnessContractKind.ACTIVITY, "publication.undo.activity", "1"),
        "undo-publication:run-1",
        1,
        last_event_sequence=4,
    )
    budgets = HarnessGraphBudgetState(
        (
            HarnessBudgetCounterState("node_activations", 100, used=5),
            HarnessBudgetCounterState("max_parallelism", 2),
            HarnessBudgetCounterState("max_active_nodes", 4),
        )
    )
    nodes = (fork, running, terminal, join_node, waiting)
    joins = (join,)
    loops = (loop,)
    waits = (wait,)
    compensations = (compensation,)
    if reverse_inputs:
        nodes = tuple(reversed(nodes))
        joins = tuple(reversed(joins))
        loops = tuple(reversed(loops))
        waits = tuple(reversed(waits))
        compensations = tuple(reversed(compensations))
    return HarnessGraphState(
        run_id="run-1",
        graph_ref=_graph_ref(),
        lifecycle="running",
        node_instances=nodes,
        active_activities=(activity,),
        join_states=joins,
        loop_counters=loops,
        wait_registrations=waits,
        compensation_stack=compensations,
        budgets=budgets,
        last_event_sequence=10,
        metadata={"accepted_observation_ref": _sha("observations")},
    )


def _minimal_state(
    *,
    nodes: tuple[HarnessNodeInstanceState, ...],
    activities: tuple[HarnessActiveActivityState, ...] = (),
    waits: tuple[HarnessWaitRegistration, ...] = (),
    joins: tuple[HarnessJoinState, ...] = (),
    loops: tuple[HarnessLoopCounterState, ...] = (),
    compensations: tuple[HarnessCompensationEntry, ...] = (),
    budgets: HarnessGraphBudgetState | None = None,
    lifecycle: str = "running",
    outcome: str = "none",
    terminal_reason_code: str | None = None,
    terminal_evidence_ref: str | None = None,
) -> HarnessGraphState:
    last_sequence = max(
        [
            0,
            *(item.last_event_sequence for item in nodes),
            *(item.dispatched_sequence for item in activities),
            *(item.last_event_sequence for item in waits),
            *(item.last_event_sequence for item in joins),
            *(item.last_event_sequence for item in loops),
            *(item.last_event_sequence for item in compensations),
        ]
    )
    return HarnessGraphState(
        run_id="run-1",
        graph_ref=_graph_ref(),
        lifecycle=lifecycle,
        outcome=outcome,
        node_instances=nodes,
        active_activities=activities,
        wait_registrations=waits,
        join_states=joins,
        loop_counters=loops,
        compensation_stack=compensations,
        budgets=(
            HarnessGraphBudgetState(
                (
                    HarnessBudgetCounterState("max_parallelism", 4),
                    HarnessBudgetCounterState("max_active_nodes", 8),
                )
            )
            if budgets is None
            else budgets
        ),
        last_event_sequence=last_sequence,
        terminal_reason_code=terminal_reason_code,
        terminal_evidence_ref=terminal_evidence_ref,
    )


def _executable_node(
    identity: HarnessNodeInstanceIdentity,
    status: str,
    *,
    attempt: int,
    step_status: str | None = None,
    output_refs=None,
    evidence_refs=(),
    activation_sequence: int = 0,
    last_event_sequence: int | None = None,
    metadata=None,
) -> HarnessNodeInstanceState:
    return HarnessNodeInstanceState(
        identity=identity,
        node_kind="executable",
        status=status,
        step_id=identity.node_id,
        step_ref=_ref(
            HarnessContractKind.STEP,
            f"research:{identity.node_id}",
            "1",
        ),
        step_status=step_status or _default_step_status(status),
        attempt=attempt,
        output_refs=output_refs or {},
        evidence_refs=tuple(evidence_refs),
        activation_sequence=activation_sequence,
        last_event_sequence=(
            activation_sequence if last_event_sequence is None else last_event_sequence
        ),
        metadata=metadata or {},
    )


def _control_node(
    identity: HarnessNodeInstanceIdentity,
    *,
    node_kind: str,
    status: str,
    sequence: int,
) -> HarnessNodeInstanceState:
    return HarnessNodeInstanceState(
        identity=identity,
        node_kind=node_kind,
        status=status,
        activation_sequence=sequence,
        last_event_sequence=sequence,
    )


def _wait_node(
    identity: HarnessNodeInstanceIdentity,
    *,
    sequence: int,
) -> HarnessNodeInstanceState:
    return HarnessNodeInstanceState(
        identity=identity,
        node_kind="wait",
        status="waiting",
        activation_sequence=sequence,
        last_event_sequence=sequence,
    )


def _activity(
    node_instance_id: str,
    *,
    attempt: int,
    activity_id: str = "activity-1",
    idempotency_key: str = "activity-idempotency-key",
    fencing_generation: int = 1,
    dispatched_sequence: int = 2,
) -> HarnessActiveActivityState:
    return HarnessActiveActivityState(
        activity_id,
        _ref(HarnessContractKind.ACTIVITY, "worker.activity", "1"),
        node_instance_id,
        attempt,
        idempotency_key,
        fencing_generation,
        dispatched_sequence,
    )


def _default_step_status(status: str) -> str:
    return {
        "pending": "pending",
        "ready": "pending",
        "running": "running",
        "waiting": "waiting_approval",
        "cancel_requested": "running",
        "compensating": "running",
        "succeeded": "succeeded",
        "failed": "failed",
        "cancelled": "skipped",
        "halted": "halted",
        "skipped": "skipped",
        "compensated": "succeeded",
    }[status]


def _wait_registration(
    node_instance_id: str,
    *,
    sequence: int,
    wait_id: str = "approval-wait",
    status: str = "registered",
    resolution_event_ref: str | None = None,
) -> HarnessWaitRegistration:
    return HarnessWaitRegistration(
        wait_id,
        node_instance_id,
        "approval",
        _sha("correlation"),
        _sha("tenant-scope"),
        _sha("identity-scope"),
        "editor.approval@1",
        sequence,
        status=status,
        resolution_event_ref=resolution_event_ref,
        last_event_sequence=sequence,
    )


def _identity(
    node_id: str,
    *,
    ordinal: int,
    branch_path: tuple[str, ...] = (),
    iteration_vector: tuple[HarnessLoopIteration, ...] = (),
) -> HarnessNodeInstanceIdentity:
    return HarnessNodeInstanceIdentity(
        "run-1",
        _graph_ref().checksum,
        node_id,
        branch_path,
        iteration_vector,
        ordinal,
    )


def _graph_ref() -> HarnessGraphReference:
    return HarnessGraphReference(
        "workflow-graph",
        _ref(HarnessContractKind.WORKFLOW, "research", "2"),
        NORMALIZED_HARNESS_GRAPH_SCHEMA,
        HARNESS_GRAPH_COMPILER_VERSION,
        HARNESS_CONDITION_POLICY_VERSION,
        _sha("graph"),
    )


def _ref(
    kind: HarnessContractKind,
    contract_id: str,
    version: str,
) -> HarnessContractReference:
    return HarnessContractReference(kind, contract_id, version)


def _sha(value: str) -> str:
    return canonical_checksum({"value": value})
