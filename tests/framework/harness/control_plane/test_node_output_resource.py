from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.graph.reference import HarnessGraphReference
from framework.harness.control_plane.node_output import (
    HarnessAdmittedGraphActivityAttempt,
    HarnessCommittedNodeOutputReceipt,
    HarnessNodeOutputAttemptStatus,
    HarnessNodeOutputCandidate,
    HarnessNodeOutputCommit,
    HarnessNodeOutputCommitGuard,
    HarnessNodeOutputCommitRejectedError,
    HarnessNodeOutputLease,
    HarnessNodeOutputResourceIdentity,
    HarnessNodeOutputStagedWrite,
    HarnessNodeOutputStaleOwnerError,
    InMemoryHarnessNodeOutputResource,
)
from framework.harness.graph.canonical import canonical_checksum
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.harness.graph.versioning import (
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_COMPILER_VERSION,
    NORMALIZED_HARNESS_GRAPH_SCHEMA,
)


_NOW = datetime(2026, 8, 15, 8, 0, tzinfo=UTC)


def test_node_output_records_round_trip_with_stable_checksums() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity()
    identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
    admission = _admission(activity, owner_attempt_id="physical-attempt-1")
    lease = resource.acquire_after_admission(activity, admission)
    candidate = _candidate("first")
    staged = resource.stage(lease, candidate, staged_at=_NOW + timedelta(seconds=1))
    commit = resource.commit(
        staged,
        _success_guard(),
        committed_at=_NOW + timedelta(seconds=2),
    )

    assert HarnessNodeOutputResourceIdentity.from_dict(identity.to_dict()) == identity
    assert HarnessAdmittedGraphActivityAttempt.from_dict(admission.to_dict()) == admission
    assert HarnessNodeOutputLease.from_dict(lease.to_dict()) == lease
    assert HarnessNodeOutputCandidate.from_dict(candidate.to_dict()) == candidate
    assert HarnessNodeOutputStagedWrite.from_dict(staged.to_dict()) == staged
    assert HarnessNodeOutputCommit.from_dict(commit.to_dict()) == commit
    assert resource.committed_output(identity) == commit


def test_committed_node_output_receipt_round_trips_and_binds_payload() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity()
    identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
    admission = _admission(activity, owner_attempt_id="physical-attempt-1")
    lease = resource.acquire_after_admission(activity, admission)
    payload = {"report": "reader-repair-result"}
    candidate = HarnessNodeOutputCandidate(
        output_refs={"report": canonical_checksum(payload)},
        evidence_refs=(_sha("evidence-receipt"),),
    )
    staged = resource.stage(lease, candidate, staged_at=_NOW)
    commit = resource.commit(staged, _success_guard(), committed_at=_NOW)
    receipt = HarnessCommittedNodeOutputReceipt(
        graph_definition_checksum=_sha("definition"),
        binding_id="repair-result-commit",
        receipt_input_key="repair_result_commit",
        producer_activity_id="analyze",
        producer_activity_ref=activity.activity_ref,
        resource=identity,
        commit=commit,
        output_key="report",
    )

    restored = HarnessCommittedNodeOutputReceipt.from_dict(receipt.to_dict())

    assert restored == receipt
    assert restored.output_ref == canonical_checksum(payload)
    assert restored.receipt_ref.startswith("sha256:")
    restored.assert_matches_payload(payload)
    with pytest.raises(HarnessValidationError) as raised:
        restored.assert_matches_payload({"report": "forged"})
    assert raised.value.code == "graph_committed_node_output_payload_mismatch"
    with pytest.raises(HarnessValidationError) as noncanonical:
        restored.assert_matches_payload(object())
    assert noncanonical.value.code == "graph_committed_node_output_payload_invalid"


def test_committed_node_output_receipt_rejects_output_ref_tampering() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity()
    identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
    admission = _admission(activity, owner_attempt_id="physical-attempt-1")
    lease = resource.acquire_after_admission(activity, admission)
    staged = resource.stage(lease, _candidate("first"), staged_at=_NOW)
    commit = resource.commit(staged, _success_guard(), committed_at=_NOW)
    receipt = HarnessCommittedNodeOutputReceipt(
        graph_definition_checksum=_sha("definition"),
        binding_id="repair-result-commit",
        receipt_input_key="repair_result_commit",
        producer_activity_id="analyze",
        producer_activity_ref=activity.activity_ref,
        resource=identity,
        commit=commit,
        output_key="report",
    ).to_dict()
    receipt["output_ref"] = _sha("forged")

    with pytest.raises(HarnessValidationError) as raised:
        HarnessCommittedNodeOutputReceipt.from_dict(receipt)

    assert (
        raised.value.code
        == "graph_committed_node_output_receipt_output_mismatch"
    )


def test_node_output_contract_rejects_nested_candidate_tampering() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity()
    admission = _admission(activity, owner_attempt_id="physical-attempt-1")
    lease = resource.acquire_after_admission(activity, admission)
    staged = resource.stage(lease, _candidate("first"), staged_at=_NOW)
    commit = resource.commit(staged, _success_guard(), committed_at=_NOW)
    payload = commit.to_dict()
    payload["candidate"]["output_refs"]["report"] = _sha("tampered")

    with pytest.raises(HarnessValidationError) as captured:
        HarnessNodeOutputCommit.from_dict(payload)

    assert captured.value.code == "graph_node_output_candidate_checksum_invalid"


def test_resource_owned_generation_fences_independent_local_attempt_counters() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity(fencing_generation=41)
    identity = HarnessNodeOutputResourceIdentity.for_activity(activity)
    first_admission = _admission(
        activity,
        owner_attempt_id="physical-attempt-1",
        local_attempt_no=1,
    )
    first = resource.acquire_after_admission(activity, first_admission)
    first_stage = resource.stage(first, _candidate("first"), staged_at=_NOW)
    second_admission = _admission(
        activity,
        owner_attempt_id="physical-attempt-2",
        local_attempt_no=1,
        admitted_at=_NOW + timedelta(seconds=1),
    )
    second = resource.acquire_after_admission(activity, second_admission)

    assert first_admission.local_attempt_no == second_admission.local_attempt_no == 1
    assert activity.fencing_generation == 41
    assert first.generation == 1
    assert second.generation == 2
    assert second.previous_lease_ref == first.lease_ref
    assert resource.current_lease(identity) == second

    with pytest.raises(HarnessNodeOutputStaleOwnerError) as stale_stage:
        resource.stage(first, _candidate("first"), staged_at=_NOW)
    with pytest.raises(HarnessNodeOutputStaleOwnerError) as stale_commit:
        resource.commit(first_stage, _success_guard(), committed_at=_NOW)

    assert stale_stage.value.code == "graph_node_output_stale_owner"
    assert stale_commit.value.code == "graph_node_output_stale_owner"
    assert resource.committed_output(identity) is None

    second_stage = resource.stage(
        second,
        _candidate("second"),
        staged_at=_NOW + timedelta(seconds=2),
    )
    committed = resource.commit(
        second_stage,
        _success_guard(),
        committed_at=_NOW + timedelta(seconds=3),
    )

    assert committed.owner_attempt_id == "physical-attempt-2"
    assert committed.generation == 2
    assert resource.committed_output(identity) == committed
    assert (
        resource.commit(
            second_stage,
            _success_guard(),
            committed_at=_NOW + timedelta(seconds=4),
        )
        == committed
    )


def test_superseded_admission_cannot_reacquire_a_new_generation() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity()
    first_admission = _admission(activity, owner_attempt_id="physical-attempt-1")
    first = resource.acquire_after_admission(activity, first_admission)
    second = resource.acquire_after_admission(
        activity,
        _admission(
            activity,
            owner_attempt_id="physical-attempt-2",
            admitted_at=_NOW + timedelta(seconds=1),
        ),
    )

    with pytest.raises(HarnessNodeOutputStaleOwnerError) as captured:
        resource.acquire_after_admission(activity, first_admission)

    assert captured.value.code == "graph_node_output_stale_owner"
    assert resource.current_lease(first.resource) == second


def test_revoked_admission_cannot_reacquire_or_publish() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity()
    admission = _admission(activity, owner_attempt_id="physical-attempt-1")
    lease = resource.acquire_after_admission(activity, admission)

    assert resource.revoke(lease) is True
    assert resource.current_lease(lease.resource) is None

    with pytest.raises(HarnessNodeOutputStaleOwnerError):
        resource.acquire_after_admission(activity, admission)
    with pytest.raises(HarnessNodeOutputStaleOwnerError):
        resource.stage(lease, _candidate("late"), staged_at=_NOW)

    assert resource.committed_output(lease.resource) is None


def test_physical_owner_identity_is_immutable() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity()
    resource.acquire_after_admission(
        activity,
        _admission(activity, owner_attempt_id="physical-attempt-1"),
    )

    with pytest.raises(HarnessValidationError) as captured:
        resource.acquire_after_admission(
            activity,
            _admission(
                activity,
                owner_attempt_id="physical-attempt-1",
                admitted_at=_NOW + timedelta(seconds=1),
            ),
        )

    assert captured.value.code == "graph_node_output_owner_identity_conflict"


@pytest.mark.parametrize(
    ("guard", "error_code"),
    [
        (
            HarnessNodeOutputCommitGuard(
                attempt_status=HarnessNodeOutputAttemptStatus.INDETERMINATE,
                termination_confirmed=True,
                descendants_determinate=False,
            ),
            "graph_node_output_indeterminate",
        ),
        (
            HarnessNodeOutputCommitGuard(
                attempt_status=HarnessNodeOutputAttemptStatus.TIMED_OUT,
                termination_confirmed=False,
                descendants_determinate=True,
            ),
            "graph_node_output_termination_unconfirmed",
        ),
        (
            HarnessNodeOutputCommitGuard(
                attempt_status=HarnessNodeOutputAttemptStatus.FAILED,
                termination_confirmed=True,
                descendants_determinate=True,
            ),
            "graph_node_output_attempt_not_succeeded",
        ),
    ],
)
def test_normal_output_commit_fails_closed_on_attempt_state(
    guard: HarnessNodeOutputCommitGuard,
    error_code: str,
) -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity()
    lease = resource.acquire_after_admission(
        activity,
        _admission(activity, owner_attempt_id="physical-attempt-1"),
    )
    staged = resource.stage(lease, _candidate("guarded"), staged_at=_NOW)

    with pytest.raises(HarnessNodeOutputCommitRejectedError) as captured:
        resource.commit(staged, guard, committed_at=_NOW)

    assert captured.value.code == error_code
    assert resource.committed_output(lease.resource) is None


def test_admission_must_match_the_checksum_bound_graph_activity() -> None:
    resource = InMemoryHarnessNodeOutputResource()
    activity = _activity()
    other = _activity(attempt=2)
    admission = _admission(other, owner_attempt_id="physical-attempt-1")

    with pytest.raises(HarnessValidationError) as captured:
        resource.acquire_after_admission(activity, admission)

    assert captured.value.code == "graph_node_output_admission_mismatch"
    assert "activity_id" in captured.value.details["mismatches"]


def _activity(
    *,
    attempt: int = 1,
    fencing_generation: int = 1,
) -> HarnessGraphActivity:
    return HarnessGraphActivity(
        run_id="run-1",
        graph_ref=_graph_ref(),
        node_id="analyze",
        node_instance_id="hni-analyze-1",
        step_ref=_ref(HarnessContractKind.STEP, "research:analyze"),
        worker_ref=_ref(HarnessContractKind.WORKER, "research-worker"),
        activity_ref=_ref(HarnessContractKind.ACTIVITY, "research-activity"),
        attempt=attempt,
        input_ref=_sha("input"),
        causal_decision_checksum=_sha(f"decision-{attempt}"),
        causal_decision_sequence=attempt,
        fencing_generation=fencing_generation,
        tenant_scope_ref=_sha("tenant"),
        identity_scope_ref=_sha("identity"),
        subject_scope_ref=_sha("subject"),
    )


def _admission(
    activity: HarnessGraphActivity,
    *,
    owner_attempt_id: str,
    local_attempt_no: int = 1,
    admitted_at: datetime = _NOW,
) -> HarnessAdmittedGraphActivityAttempt:
    return HarnessAdmittedGraphActivityAttempt(
        activity_id=activity.activity_id,
        activity_checksum=activity.activity_checksum,
        owner_attempt_id=owner_attempt_id,
        operation_id=f"graph-activity://{activity.run_id}/{activity.node_instance_id}",
        operation_kind="graph_activity",
        idempotency_key=activity.idempotency_key,
        local_attempt_no=local_attempt_no,
        parent_attempt_id=None,
        retry_credit_id=None,
        admitted_at=admitted_at,
    )


def _candidate(label: str) -> HarnessNodeOutputCandidate:
    return HarnessNodeOutputCandidate(
        output_refs={"report": _sha(f"report-{label}")},
        evidence_refs=(_sha(f"evidence-{label}"),),
    )


def _success_guard() -> HarnessNodeOutputCommitGuard:
    return HarnessNodeOutputCommitGuard(
        attempt_status=HarnessNodeOutputAttemptStatus.SUCCEEDED,
        termination_confirmed=True,
        descendants_determinate=True,
    )


def _graph_ref() -> HarnessGraphReference:
    return HarnessGraphReference(
        "graph",
        _ref(HarnessContractKind.WORKFLOW, "research", version="2"),
        NORMALIZED_HARNESS_GRAPH_SCHEMA,
        HARNESS_GRAPH_COMPILER_VERSION,
        HARNESS_CONDITION_POLICY_VERSION,
        _sha("graph"),
    )


def _ref(
    kind: HarnessContractKind,
    contract_id: str,
    *,
    version: str = "1",
) -> HarnessContractReference:
    return HarnessContractReference(kind, contract_id, version)


def _sha(value: str) -> str:
    return canonical_checksum({"value": value})
