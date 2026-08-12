from __future__ import annotations

from decimal import Decimal

import pytest

from framework.governance.budget import (
    BUDGET_SCHEMA_VERSION,
    BudgetAmounts,
    BudgetContractError,
    BudgetLimits,
    BudgetPolicy,
    BudgetDecision,
    BudgetEvent,
    BudgetUsage,
    BudgetScopeRef,
    BudgetSnapshot,
    BudgetScopeSnapshot,
    BudgetOperationRecord,
)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("llm_calls", True),
        ("llm_calls", -1),
        ("input_tokens", 1.5),
        ("output_tokens", 2**63),
        ("estimated_cost_usd", True),
        ("estimated_cost_usd", "NaN"),
        ("estimated_cost_usd", "Infinity"),
        ("estimated_cost_usd", "-0.01"),
    ],
)
def test_amounts_reject_invalid_external_values(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(BudgetContractError):
        BudgetAmounts(**{field_name: value})


def test_amounts_reject_unknown_dimensions() -> None:
    with pytest.raises(BudgetContractError, match="unknown fields"):
        BudgetAmounts.from_dict({"llm_calls": 1, "retry_credits": 2})


def test_decimal_cost_round_trip_is_canonical() -> None:
    amounts = BudgetAmounts(estimated_cost_usd=Decimal("0.1000000000004"))

    payload = amounts.to_dict()
    restored = BudgetAmounts.from_dict(payload)

    assert payload["estimated_cost_usd"] == "0.100000000000"
    assert restored.to_dict() == payload


def test_policy_digest_is_stable_and_revision_sensitive() -> None:
    policy = BudgetPolicy(
        policy_revision="policy-v1",
        limits=BudgetLimits(llm_calls=2, estimated_cost_usd="1.5"),
    )
    restored = BudgetPolicy.from_dict(policy.to_dict())

    assert restored == policy
    assert restored.digest == policy.digest
    assert BudgetPolicy(
        policy_revision="policy-v2",
        limits=policy.limits,
    ).digest != policy.digest


def test_snapshot_rejects_unknown_schema_and_fields() -> None:
    payload = {
        "schema_version": BUDGET_SCHEMA_VERSION,
        "root_scope_id": "root",
        "policy_digest": "sha256:" + "0" * 64,
        "scopes": [],
        "open_reservations": [],
        "operation_records": [],
        "last_event_id": None,
        "ledger_revision": 0,
        "raw_prompt": "must-not-be-accepted",
    }

    with pytest.raises(BudgetContractError, match="unknown fields"):
        BudgetSnapshot.from_dict(payload)

    payload.pop("raw_prompt")
    payload["schema_version"] = "newsroom.budget/v999"
    with pytest.raises(BudgetContractError, match="unsupported"):
        BudgetSnapshot.from_dict(payload)


def test_scope_requires_explicit_parent_for_non_run_scope() -> None:
    with pytest.raises(BudgetContractError, match="parent_scope_id"):
        BudgetScopeRef(
            run_id="run-1",
            scope_id="agent-1",
            scope_type="agent_loop",
            policy_revision="policy-v1",
        )


def test_decision_and_event_reason_collections_are_bounded() -> None:
    scope = BudgetScopeRef(
        run_id="run-1",
        scope_id="root",
        scope_type="run",
        policy_revision="policy-v1",
    )
    usage = BudgetUsage(
        committed=BudgetAmounts(),
        reserved=BudgetAmounts(),
        available=BudgetAmounts(),
        ledger_revision=1,
    )
    reasons = tuple(f"reason-{index}" for index in range(17))

    with pytest.raises(BudgetContractError, match="too many violations"):
        BudgetDecision(
            allowed=False,
            violations=reasons,
            projected_usage=usage,
            reservation_id=None,
            ledger_revision=1,
        )
    with pytest.raises(BudgetContractError, match="too many reason codes"):
        BudgetEvent(
            event_id="event-1",
            event_type="budget_reservation_denied",
            run_id="run-1",
            scope=scope,
            policy_digest="sha256:" + "0" * 64,
            ledger_revision=1,
            operation_id="operation-1",
            idempotency_key="key-1",
            reservation_id=None,
            amounts=BudgetAmounts(llm_calls=1),
            reason_codes=reasons,
            outcome="denied",
        )


def test_snapshot_constructor_normalizes_nested_collections_to_immutable_values() -> None:
    policy = BudgetPolicy(policy_revision="policy-v1")
    scope = BudgetScopeRef(
        run_id="run-1",
        scope_id="root",
        scope_type="run",
        policy_revision=policy.policy_revision,
    )
    snapshot = BudgetSnapshot(
        root_scope_id=scope.scope_id,
        policy_digest=policy.digest,
        scopes=[
            BudgetScopeSnapshot(
                scope=scope,
                policy=policy,
                committed=BudgetAmounts(),
                reserved=BudgetAmounts(),
            )
        ],
        open_reservations=[],
        operation_records=[],
        last_event_id=None,
        ledger_revision=0,
    )

    assert isinstance(snapshot.scopes, tuple)
    assert isinstance(snapshot.open_reservations, tuple)
    assert isinstance(snapshot.operation_records, tuple)


def test_operation_record_constructor_rejects_inconsistent_nested_identity() -> None:
    with pytest.raises(BudgetContractError, match="reservation is missing"):
        BudgetOperationRecord(
            operation_id="operation-1",
            idempotency_key="key-1",
            fingerprint="sha256:" + "0" * 64,
            reservation_id="reservation-1",
        )
