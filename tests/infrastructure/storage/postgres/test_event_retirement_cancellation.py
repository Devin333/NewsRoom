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
    ConsumerCheckpoint,
    DeliveryRecord,
    DeliveryState,
    RetirementCancellationRequest,
    SubscriptionKey,
)
from infrastructure.storage.events.postgres import (
    PostgresDurableEventStore,
    _checkpoint_checksum,
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


def test_retry_identity_excludes_fresh_authorization_audit_metadata() -> None:
    connection = _ReportConnection(_report_row(), [_item_row()])
    store = _store(connection)

    report = store.cancel_retired_subscription(
        replace(
            _request(),
            requested_at=REQUESTED_AT + timedelta(minutes=5),
            authorization_evidence_ref="authorization:decision-2",
        )
    )

    assert report.requested_at == REQUESTED_AT
    assert report.authorization_evidence_ref == "authorization:decision-1"
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_checkpoint_advance_scans_only_after_locked_durable_frontier() -> None:
    existing = _checkpoint(41, event_id="event-41", updated_at=REQUESTED_AT)
    frontier = _delivery_row(42, state="acked")
    cursor = _CheckpointCursor(
        start_sequence=1,
        existing_row=_checkpoint_row(existing),
        delivery_rows=[frontier],
        updated_row=_checkpoint_row(
            _checkpoint(42, event_id="event-42", updated_at=CANCELLED_AT)
        ),
    )
    store = object.__new__(PostgresDurableEventStore)

    result = store._advance_checkpoint(
        cursor,
        _delivery(42, state=DeliveryState.ACKED),
        updated_at=CANCELLED_AT,
    )

    assert result is not None
    assert result.highest_contiguous_terminal_sequence == 42
    assert cursor.scan_params is not None
    assert cursor.scan_params[-1] == 42
    assert cursor.checkpoint_select_for_update


def test_checkpoint_advance_without_existing_frontier_starts_at_subscription_boundary() -> None:
    cursor = _CheckpointCursor(
        start_sequence=7,
        existing_row=None,
        delivery_rows=[_delivery_row(7, state="acked")],
        inserted_row=_checkpoint_row(
            _checkpoint(7, event_id="event-7", updated_at=CANCELLED_AT)
        ),
    )
    store = object.__new__(PostgresDurableEventStore)

    result = store._advance_checkpoint(
        cursor,
        _delivery(7, state=DeliveryState.ACKED),
        updated_at=CANCELLED_AT,
    )

    assert result is not None
    assert result.highest_contiguous_terminal_sequence == 7
    assert cursor.scan_params is not None
    assert cursor.scan_params[-1] == 7


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


def _delivery(sequence: int, *, state: DeliveryState) -> DeliveryRecord:
    attempt_count = 0 if state is DeliveryState.PENDING else 1
    return DeliveryRecord(
        delivery_id=f"delivery-{sequence}",
        event_id=f"event-{sequence}",
        stream_id="stream-1",
        stream_sequence=sequence,
        subscription_id="subscription-1",
        subscription_version=1,
        consumer_id="consumer-1",
        tenant_id="tenant-1",
        state=state,
        attempt_count=attempt_count,
        created_at=REQUESTED_AT,
        updated_at=CANCELLED_AT,
    )


def _delivery_row(sequence: int, *, state: str) -> tuple[Any, ...]:
    record = _delivery(sequence, state=DeliveryState(state))
    return (
        record.delivery_id,
        record.event_id,
        record.stream_id,
        record.stream_sequence,
        record.subscription_id,
        record.subscription_version,
        record.consumer_id,
        record.consumer_effect_id,
        record.tenant_id,
        record.delivery_generation,
        record.state.value,
        record.attempt_count,
        record.available_at,
        record.lease_owner,
        record.lease_generation,
        record.lease_expires_at,
        record.first_failure_at,
        record.last_failure_at,
        record.reason_class,
        record.redacted_diagnostic,
        record.created_at,
        record.updated_at,
    )


def _checkpoint(
    sequence: int,
    *,
    event_id: str,
    updated_at: datetime,
) -> ConsumerCheckpoint:
    checksum = _checkpoint_checksum(
        subscription_id="subscription-1",
        subscription_version=1,
        stream_id="stream-1",
        tenant_id="tenant-1",
        sequence=sequence,
        event_id=event_id,
        disposition=DeliveryState.ACKED,
        updated_at=updated_at,
        checkpoint_version=1,
    )
    return ConsumerCheckpoint(
        subscription_id="subscription-1",
        subscription_version=1,
        stream_id="stream-1",
        highest_contiguous_terminal_sequence=sequence,
        last_event_id=event_id,
        terminal_disposition=DeliveryState.ACKED,
        updated_at=updated_at,
        checksum=checksum,
        checkpoint_version=1,
        tenant_id="tenant-1",
    )


def _checkpoint_row(checkpoint: ConsumerCheckpoint) -> tuple[Any, ...]:
    return (
        checkpoint.subscription_id,
        checkpoint.subscription_version,
        checkpoint.stream_id,
        checkpoint.highest_contiguous_terminal_sequence,
        checkpoint.last_event_id,
        checkpoint.terminal_disposition.value,
        checkpoint.updated_at,
        checkpoint.checksum,
        checkpoint.checkpoint_version,
        checkpoint.tenant_id,
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


class _CheckpointCursor:
    def __init__(
        self,
        *,
        start_sequence: int,
        existing_row: tuple[Any, ...] | None,
        delivery_rows: list[tuple[Any, ...]],
        inserted_row: tuple[Any, ...] | None = None,
        updated_row: tuple[Any, ...] | None = None,
    ) -> None:
        self.start_sequence = start_sequence
        self.existing_row = existing_row
        self.delivery_rows = delivery_rows
        self.inserted_row = inserted_row
        self.updated_row = updated_row
        self.current = ""
        self.scan_params: tuple[Any, ...] | None = None
        self.checkpoint_select_for_update = False

    def execute(self, query: object, params: object = None) -> None:
        normalized = " ".join(str(query).split())
        self.current = normalized
        if (
            "FROM event_consumer_checkpoints" in normalized
            and "FOR UPDATE" in normalized
        ):
            self.checkpoint_select_for_update = True
        if (
            "FROM event_deliveries" in normalized
            and "delivery_generation = 1" in normalized
        ):
            assert isinstance(params, tuple)
            self.scan_params = params

    def fetchone(self) -> tuple[Any, ...] | None:
        if "SELECT start_sequence" in self.current:
            return (self.start_sequence,)
        if "FROM event_consumer_checkpoints" in self.current:
            return self.existing_row
        if self.current.startswith("INSERT INTO event_consumer_checkpoints"):
            return self.inserted_row
        if self.current.startswith("UPDATE event_consumer_checkpoints"):
            return self.updated_row
        raise AssertionError(f"unexpected fetchone query: {self.current}")

    def fetchall(self) -> list[tuple[Any, ...]]:
        if "FROM event_deliveries" not in self.current:
            raise AssertionError(f"unexpected fetchall query: {self.current}")
        return list(self.delivery_rows)


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
