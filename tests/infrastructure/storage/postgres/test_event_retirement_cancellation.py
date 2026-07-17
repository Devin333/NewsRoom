from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from framework.events.errors import (
    EventRetirementCancellationCollisionError,
    EventStoreCorruptionError,
)
from framework.events.runtime.models import (
    DeliveryState,
    RetirementCancellationRequest,
    SubscriptionKey,
)
from infrastructure.storage.events.postgres import (
    PostgresDurableEventStore,
    _delivery_columns,
    _retirement_cancellation_report_from_postgres,
)


REQUESTED_AT = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
CANCELLED_AT = REQUESTED_AT + timedelta(seconds=1)


def test_delivery_column_projection_supports_a_qualified_table_alias() -> None:
    columns = _delivery_columns("delivery").split(", ")

    assert len(columns) == 22
    assert columns[0] == "delivery.delivery_id"
    assert columns[-1] == "delivery.updated_at"
    assert all(column.startswith("delivery.") for column in columns)
    assert _delivery_columns().split(", ")[0] == "delivery_id"


def test_retirement_cancellation_report_decoder_validates_linked_delivery() -> None:
    cursor = _ReportCursor(item_rows=[_item_row()])

    report = _retirement_cancellation_report_from_postgres(cursor, _report_row())

    assert report.cancellation_id == "cancel-1"
    assert report.subscription == SubscriptionKey("subscription-1", 1)
    assert report.completed
    assert report.cancelled_count == 1
    assert report.items[0].previous_state is DeliveryState.PENDING
    assert report.items[0].previous_attempt_count == 0
    assert report.items[0].terminal_state is DeliveryState.DROPPED
    assert cursor.params == ("tenant-1", "cancel-1", 101)


@pytest.mark.parametrize(
    ("linked_state", "linked_attempt_count"),
    [
        ("acked", 1),
        ("dropped", 0),
    ],
)
def test_retirement_cancellation_report_decoder_rejects_audit_drift(
    linked_state: str,
    linked_attempt_count: int,
) -> None:
    cursor = _ReportCursor(
        item_rows=[
            _item_row(
                linked_state=linked_state,
                linked_attempt_count=linked_attempt_count,
            )
        ]
    )

    with pytest.raises(
        EventStoreCorruptionError,
        match="disagrees with its delivery disposition",
    ):
        _retirement_cancellation_report_from_postgres(cursor, _report_row())


@pytest.mark.parametrize(
    "changes",
    [
        {"linked_attempt_count": 2},
        {"linked_reason_class": "manual_drop"},
        {
            "linked_lease_owner": "stale-worker",
            "linked_lease_generation": 2,
            "linked_lease_expires_at": CANCELLED_AT + timedelta(seconds=30),
        },
        {"linked_updated_at": CANCELLED_AT + timedelta(seconds=1)},
    ],
)
def test_retirement_cancellation_report_decoder_rejects_terminal_drift(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(
        EventStoreCorruptionError,
        match="disagrees with its delivery disposition",
    ):
        _retirement_cancellation_report_from_postgres(
            _ReportCursor(item_rows=[_item_row(**changes)]),
            _report_row(),
        )


def test_retirement_cancellation_report_decoder_rejects_subscription_drift() -> None:
    drifted = list(_item_row())
    drifted[7] = "subscription-2"
    drifted[18] = "subscription-2"

    with pytest.raises(
        EventStoreCorruptionError,
        match="crossed subscription scope",
    ):
        _retirement_cancellation_report_from_postgres(
            _ReportCursor(item_rows=[tuple(drifted)]),
            _report_row(),
        )


def test_retirement_cancellation_report_decoder_rejects_missing_audit_item() -> None:
    with pytest.raises(
        EventStoreCorruptionError,
        match="missing audit items",
    ):
        _retirement_cancellation_report_from_postgres(
            _ReportCursor(item_rows=[]),
            _report_row(),
        )


def test_exact_retirement_cancellation_retry_returns_original_report() -> None:
    request = _request()
    connection = _ReportConnection(_report_row(), [_item_row()])
    store = _store(connection)

    report = store.cancel_retired_subscription(request)

    assert report.cancellation_id == request.cancellation_id
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed
    assert connection.cursor_value.queries[0].startswith(
        "SELECT pg_advisory_xact_lock"
    )


def test_changed_retirement_cancellation_retry_rolls_back_with_typed_collision() -> None:
    connection = _ReportConnection(_report_row(), [_item_row()])
    store = _store(connection)

    with pytest.raises(EventRetirementCancellationCollisionError):
        store.cancel_retired_subscription(
            replace(_request(), operator_reason="another authorized operation")
        )

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed


def _request() -> RetirementCancellationRequest:
    return RetirementCancellationRequest(
        cancellation_id="cancel-1",
        subscription=SubscriptionKey("subscription-1", 1),
        requested_at=REQUESTED_AT,
        operator_id="operator-1",
        operator_reason="retire obsolete consumer",
        authorization_evidence_ref="authorization:decision-1",
        tenant_id="tenant-1",
        limit=100,
    )


def _report_row() -> tuple[Any, ...]:
    return (
        "cancel-1",
        "tenant-1",
        "tenant-1",
        "subscription-1",
        1,
        REQUESTED_AT,
        CANCELLED_AT,
        "operator-1",
        "retire obsolete consumer",
        "authorization:decision-1",
        100,
        1,
        0,
        False,
    )


def _item_row(
    *,
    linked_state: str = "dropped",
    linked_attempt_count: int = 1,
    linked_reason_class: str = "subscription_retired",
    linked_lease_owner: str | None = None,
    linked_lease_generation: int | None = None,
    linked_lease_expires_at: datetime | None = None,
    linked_updated_at: datetime = CANCELLED_AT,
) -> tuple[Any, ...]:
    return (
        "tenant-1",
        "tenant-1",
        "cancel-1",
        "delivery-1",
        "event-1",
        "stream-1",
        1,
        "subscription-1",
        1,
        1,
        "pending",
        0,
        None,
        "dropped",
        CANCELLED_AT,
        "event-1",
        "stream-1",
        1,
        "subscription-1",
        1,
        1,
        linked_state,
        linked_attempt_count,
        "tenant-1",
        linked_reason_class,
        linked_lease_owner,
        linked_lease_generation,
        linked_lease_expires_at,
        linked_updated_at,
    )


class _ReportCursor:
    def __init__(self, *, item_rows: list[tuple[Any, ...]]) -> None:
        self.item_rows = item_rows
        self.params: tuple[Any, ...] | None = None
        self.queries: list[str] = []

    def __enter__(self) -> _ReportCursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: object, params: object = None) -> None:
        normalized = " ".join(str(query).split())
        self.queries.append(normalized)
        if "FROM event_retirement_cancellation_items" in normalized:
            assert isinstance(params, tuple)
            self.params = params

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self.item_rows)


class _TransactionCursor(_ReportCursor):
    def __init__(
        self,
        report_row: tuple[Any, ...],
        item_rows: list[tuple[Any, ...]],
    ) -> None:
        super().__init__(item_rows=item_rows)
        self.report_row = report_row

    def fetchone(self) -> tuple[Any, ...]:
        return self.report_row


class _ReportConnection:
    autocommit = False

    def __init__(
        self,
        report_row: tuple[Any, ...],
        item_rows: list[tuple[Any, ...]],
    ) -> None:
        self.cursor_value = _TransactionCursor(report_row, item_rows)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def __enter__(self) -> _ReportConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def cursor(self) -> _TransactionCursor:
        return self.cursor_value

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def _store(connection: _ReportConnection) -> PostgresDurableEventStore:
    return PostgresDurableEventStore(
        "postgresql://localhost/newsroom_test",
        connection_factory=lambda: connection,
    )
