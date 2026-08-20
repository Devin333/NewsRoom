from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from framework.events import (
    CanonicalBudgetEventSink,
    DurableBudgetFactResolver,
    EventRuntime,
    EventSchemaValidationError,
    EventPage,
    StreamReadRequest,
    budget_event_from_stored_event,
    default_event_schema_catalog,
)
from framework.governance.budget import (
    BudgetAmounts,
    BudgetHistoryError,
    BudgetLedger,
    BudgetLimits,
    BudgetPolicy,
    BudgetReservation,
    BudgetScopeRef,
    BudgetSettlement,
)
from framework.shared.graph_identity import GraphExecutionIdentity
from infrastructure.storage.events.sqlite import SQLiteEventStore


NOW = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)


class _TamperedRevisionReader:
    def __init__(self, delegate: SQLiteEventStore) -> None:
        self._delegate = delegate

    def get_event(self, event_id, *, tenant_id=None):  # type: ignore[no-untyped-def]
        return self._delegate.get_event(event_id, tenant_id=tenant_id)

    def get_stream_high_watermark(self, stream_id, *, tenant_id=None):  # type: ignore[no-untyped-def]
        return self._delegate.get_stream_high_watermark(
            stream_id,
            tenant_id=tenant_id,
        )

    def read_stream(self, request):  # type: ignore[no-untyped-def]
        page = self._delegate.read_stream(request)
        events = []
        for event in page.events:
            payload = dict(event.payload or {})
            payload["ledger_revision"] = int(payload["ledger_revision"]) + 1
            events.append(
                replace(
                    event,
                    candidate=replace(event.candidate, payload=payload),
                )
            )
        return EventPage(
            stream_id=page.stream_id,
            events=tuple(events),
            high_watermark=page.high_watermark,
            next_cursor=page.next_cursor,
            tenant_id=page.tenant_id,
        )


def _durable_ledger(tmp_path, *, execution_identity=None):
    store = SQLiteEventStore(tmp_path / "budget-events.sqlite3", clock=lambda: NOW)
    runtime = EventRuntime(
        store=store,
        schema_catalog=default_event_schema_catalog(),
    )
    policy = BudgetPolicy(
        policy_revision="policy-v1",
        limits=BudgetLimits(llm_calls=2, total_tokens=40),
    )
    scope = BudgetScopeRef(
        run_id="run-budget",
        scope_id="run-budget:root",
        scope_type="run",
        policy_revision=policy.policy_revision,
        execution_identity=execution_identity,
    )
    ledger = BudgetLedger(
        scope,
        policy,
        event_sink=CanonicalBudgetEventSink(
            runtime,
            tenant_id="tenant-budget",
            now_fn=lambda: NOW,
        ),
        clock_epoch_ms=lambda: 1_000,
    )
    return ledger, scope, policy, store


def _graph_execution_identity(*, activity_id: str = "activity-budget"):
    return GraphExecutionIdentity(
        run_id="run-budget",
        graph_id="research.paper-analysis",
        graph_version="4",
        graph_ref="research.paper-analysis@4",
        graph_checksum="sha256:" + "a" * 64,
        node_id="analyze",
        node_instance_id="analyze:1",
        activity_id=activity_id,
        attempt=1,
    )


def test_budget_lifecycle_round_trips_through_durable_stream(tmp_path) -> None:
    ledger, scope, policy, store = _durable_ledger(tmp_path)
    reservation = ledger.reserve(
        scope,
        BudgetAmounts(llm_calls=1, input_tokens=12, output_tokens=8),
        "operation-1",
        "idempotency-1",
    )
    assert isinstance(reservation, BudgetReservation)
    ledger.settle(
        reservation.reservation_id,
        BudgetSettlement(
            reservation_id=reservation.reservation_id,
            operation_id=reservation.operation_id,
            scope=scope,
            policy_digest=policy.digest,
            actual=BudgetAmounts(llm_calls=1, input_tokens=11, output_tokens=4),
            request_dispatched=True,
            cache_hit=False,
            outcome="succeeded",
            settled_event_id="budget-settlement-1",
        ),
    )

    resolver = DurableBudgetFactResolver(store, tenant_id="tenant-budget")
    fact = resolver.resolve(
        run_id="run-budget",
        operation_id="operation-1",
        ledger_revision=2,
    )

    assert fact is not None
    assert fact.event.event_type == "budget_reservation_settled"
    assert fact.event.amounts == BudgetAmounts(
        llm_calls=1,
        input_tokens=11,
        output_tokens=4,
    )
    page = store.read_stream(
        StreamReadRequest(
            stream_id="budget:run-budget",
            tenant_id="tenant-budget",
            limit=10,
        )
    )
    assert [event.stream_sequence for event in page.events] == [1, 2]
    assert [budget_event_from_stored_event(event) for event in page.events]
    payload_text = " ".join(str(event.payload) for event in page.events)
    for forbidden in ("raw prompt", "secret-value", "tool payload", "provider body"):
        assert forbidden not in payload_text


def test_budget_resolver_is_tenant_scoped_and_rejects_revision_gaps(tmp_path) -> None:
    ledger, scope, _, store = _durable_ledger(tmp_path)
    reservation = ledger.reserve(
        scope,
        BudgetAmounts(llm_calls=1),
        "operation-1",
        "idempotency-1",
    )
    assert isinstance(reservation, BudgetReservation)
    assert (
        DurableBudgetFactResolver(store, tenant_id="other-tenant").resolve(
            run_id="run-budget",
            operation_id="operation-1",
            ledger_revision=1,
        )
        is None
    )

    with pytest.raises(BudgetHistoryError, match="not contiguous"):
        DurableBudgetFactResolver(
            _TamperedRevisionReader(store),
            tenant_id="tenant-budget",
        ).resolve(
            run_id="run-budget",
            operation_id="operation-1",
            ledger_revision=2,
        )


def test_budget_resolver_requires_matching_expected_graph_identity(tmp_path) -> None:
    identity = _graph_execution_identity()
    ledger, scope, _, store = _durable_ledger(
        tmp_path,
        execution_identity=identity,
    )
    reservation = ledger.reserve(
        scope,
        BudgetAmounts(llm_calls=1),
        "operation-1",
        "idempotency-1",
    )
    assert isinstance(reservation, BudgetReservation)

    resolver = DurableBudgetFactResolver(store, tenant_id="tenant-budget")
    fact = resolver.resolve(
        run_id="run-budget",
        operation_id="operation-1",
        ledger_revision=1,
        expected_identity=identity,
    )
    assert fact is not None
    assert fact.event.scope.execution_identity == identity

    with pytest.raises(BudgetHistoryError, match="expected execution"):
        resolver.resolve(
            run_id="run-budget",
            operation_id="operation-1",
            ledger_revision=1,
            expected_identity=_graph_execution_identity(activity_id="other-activity"),
        )


def test_budget_resolver_expected_graph_identity_fails_closed_for_legacy_scope(tmp_path) -> None:
    ledger, scope, _, store = _durable_ledger(tmp_path)
    reservation = ledger.reserve(
        scope,
        BudgetAmounts(llm_calls=1),
        "operation-1",
        "idempotency-1",
    )
    assert isinstance(reservation, BudgetReservation)

    with pytest.raises(BudgetHistoryError, match="expected execution"):
        DurableBudgetFactResolver(store, tenant_id="tenant-budget").resolve(
            run_id="run-budget",
            operation_id="operation-1",
            ledger_revision=1,
            expected_identity=_graph_execution_identity(),
        )


def test_budget_schema_rejects_arbitrary_nested_metadata(tmp_path) -> None:
    ledger, scope, _, store = _durable_ledger(tmp_path)
    reservation = ledger.reserve(
        scope,
        BudgetAmounts(llm_calls=1),
        "operation-1",
        "idempotency-1",
    )
    assert isinstance(reservation, BudgetReservation)
    stored = store.read_stream(
        StreamReadRequest(
            stream_id="budget:run-budget",
            tenant_id="tenant-budget",
            limit=10,
        )
    ).events[0]
    payload = dict(stored.payload or {})
    payload["reservation"] = {
        **dict(payload["reservation"]),
        "raw_prompt": "must be rejected",
    }

    with pytest.raises(EventSchemaValidationError):
        default_event_schema_catalog().validate(
            stored.event_type,
            stored.data_schema,
            payload,
        )
