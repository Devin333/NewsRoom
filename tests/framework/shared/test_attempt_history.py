from __future__ import annotations

from framework.shared.attempt_events import attempt_rejection_event_payload
from framework.shared.attempt_history import (
    LEGACY_ATTEMPT_SEMANTICS,
    SCOPE_AWARE_ATTEMPT_SEMANTICS,
    decode_attempt_history,
)
from framework.shared.attempts import (
    AdmissionResult,
    AttemptContext,
    DeadlineAdmissionPolicy,
    LocalRetryBudget,
    RetryCreditLedger,
)
from framework.events.schema import default_event_schema_catalog


def test_legacy_attempt_history_is_diagnostic_only_and_not_upcast() -> None:
    projection = decode_attempt_history(
        {
            "event_type": "step_started",
            "schema_version": "newsroom.event.v1",
            "event_id": "legacy-1",
            "sequence": 7,
            "payload": {
                "fencing_token": 9,
                "max_total_attempts": 4,
                "outcome": {"budget": {"max_attempts": 4, "used": 2}},
            },
        }
    )

    assert projection is not None
    assert projection.semantics == LEGACY_ATTEMPT_SEMANTICS
    assert projection.legacy_fields["payload.fencing_token"] == 9
    assert projection.legacy_fields["payload.max_total_attempts"] == 4
    assert "max_total_retries" not in projection.to_dict()
    assert projection.live_replay_permitted is False


def test_new_attempt_history_requires_scope_identity_and_has_no_generic_fence() -> None:
    context = AttemptContext.create(
        attempt_id="attempt-1",
        operation_id="step:one",
        operation_kind="graph_step",
        idempotency_key="graph:one",
        local_attempt_no=1,
        local_budget=LocalRetryBudget(max_attempts=2),
        admission_details={
            "now_monotonic": 1.0,
            "requested_until": 4.0,
            "parent_available_until": None,
            "root_available_until": None,
            "completion_until": 4.0,
            "effective_deadline": 4.0,
            "execution_window_seconds": 3.0,
            "min_start_window_seconds": 0.0,
            "cancellation_grace_seconds": 0.0,
            "completion_reserve_seconds": 0.0,
            "local_budget": LocalRetryBudget(max_attempts=2).snapshot(),
            "root_retry_credits": RetryCreditLedger(max_total_retries=1).snapshot(),
        },
    )
    payload = {
        "execution_id": "run-1",
        "operation_id": context.operation_id,
        "operation_kind": context.operation_kind,
        "idempotency_key": context.idempotency_key,
        "started": True,
        "attempt_id": context.attempt_id,
        "local_attempt_no": context.local_attempt_no,
        "retry_credit_id": None,
        "parent_attempt_id": None,
        "deadline_calculation": {
            "now_monotonic": 1.0,
            "requested_until": 4.0,
            "parent_available_until": None,
            "root_available_until": None,
            "completion_until": 4.0,
            "effective_deadline": 4.0,
            "execution_window_seconds": 3.0,
            "min_start_window_seconds": 0.0,
            "cancellation_grace_seconds": 0.0,
            "completion_reserve_seconds": 0.0,
        },
        "local_budget": {
            "max_attempts": 2,
            "used_attempts": 1,
            "remaining_attempts": 1,
        },
        "root_retry_credits": {
            "max_total_retries": 1,
            "used_retries": 0,
            "remaining_retries": 1,
        },
    }
    projection = decode_attempt_history(
        {
            "event_type": "attempt_started",
            "data_schema": "newsroom.attempt-event/v1",
            "event_id": "new-1",
            "stream_sequence": 3,
            "payload": payload,
        }
    )

    assert projection is not None
    assert projection.semantics == SCOPE_AWARE_ATTEMPT_SEMANTICS
    assert projection.local_attempt_no == 1
    assert projection.deadline_calculation["effective_deadline"] == 4.0
    assert projection.local_budget["max_attempts"] == 2
    assert projection.root_retry_credits["max_total_retries"] == 1
    assert projection.legacy_fields == {}
    assert "fencing_token" not in projection.to_dict()
    catalog = default_event_schema_catalog()
    catalog.validate("attempt_started", "newsroom.attempt-event/v1", payload)


def test_rejection_payload_omits_attempt_identity_and_schema_accepts_it() -> None:
    admission = AdmissionResult(
        admitted=False,
        reason_code="attempt_deadline_admission_rejected",
        effective_deadline=1.5,
        execution_window_seconds=0.5,
        details={
            "now_monotonic": 1.0,
            "requested_until": 6.0,
            "parent_available_until": 2.0,
            "root_available_until": None,
            "completion_until": 2.0,
            "effective_deadline": 1.5,
            "execution_window_seconds": 0.5,
            "min_start_window_seconds": 1.0,
            "cancellation_grace_seconds": 0.5,
            "completion_reserve_seconds": 0.0,
            "local_budget": LocalRetryBudget(max_attempts=2).snapshot(),
            "root_retry_credits": RetryCreditLedger(max_total_retries=1).snapshot(),
        },
    )
    payload = attempt_rejection_event_payload(
        execution_id="run-1",
        operation_id="step:one",
        operation_kind="graph_step",
        idempotency_key="graph:one",
        reason_code="attempt_deadline_admission_rejected",
        admission=admission,
    )

    assert "attempt_id" not in payload
    assert "local_attempt_no" not in payload
    default_event_schema_catalog().validate(
        "attempt_admission_rejected",
        "newsroom.attempt-event/v1",
        payload,
    )


def test_resource_specific_fence_is_not_decoded_as_legacy_attempt_identity() -> None:
    projection = decode_attempt_history(
        {
            "event_type": "step_finished",
            "schema_version": "newsroom.event.v1",
            "payload": {
                "step_id": "s1",
                "metadata": {
                    "resource_id": "data-buffer:s1",
                    "fencing_token": 7,
                    "owner_attempt_id": "attempt-7",
                },
            },
        }
    )

    assert projection is None
