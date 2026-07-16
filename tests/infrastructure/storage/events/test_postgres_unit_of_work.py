from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from framework.events.errors import (
    EventStoreContentionError,
    EventStoreError,
    EventStoreUnavailableError,
)

psycopg = pytest.importorskip("psycopg")


class _LifecycleConnection:
    def __init__(self, *, rollback_error: BaseException | None = None) -> None:
        self.autocommit = False
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0
        self.rollback_error = rollback_error

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1
        if self.rollback_error is not None:
            raise self.rollback_error

    def close(self) -> None:
        self.closes += 1


class _LifecycleFactory:
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.calls = 0

    def __call__(self) -> Any:
        self.calls += 1
        return self.connection


class _AcquireFailureConnection(_LifecycleConnection):
    @property
    def autocommit(self) -> bool:
        raise psycopg.OperationalError("connection initialization failed")

    @autocommit.setter
    def autocommit(self, value: bool) -> None:
        pass


class _AdvisoryCursor:
    def __init__(self, *try_results: bool) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self._try_results = list(try_results)
        self._current_result: tuple[bool] | None = None

    def execute(self, query: object, params: tuple[object, ...]) -> None:
        sql = str(query)
        self.executed.append((sql, params))
        if "pg_try_advisory" in sql:
            self._current_result = (self._try_results.pop(0),)

    def fetchone(self) -> tuple[bool] | None:
        result = self._current_result
        self._current_result = None
        return result


def _store(factory: _LifecycleFactory) -> Any:
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    return PostgresDurableEventStore(
        "postgresql://example/test",
        connection_factory=factory,
    )


def test_initial_retired_subscription_is_rejected_before_connection_acquisition() -> None:
    from framework.events.runtime import DurableSubscription, SubscriptionStatus

    connection = _LifecycleConnection()
    factory = _LifecycleFactory(connection)
    store = _store(factory)

    with pytest.raises(ValueError, match="initial RETIRED"):
        store.register_subscription(
            DurableSubscription(
                subscription_id="retired-subscription",
                subscription_version=1,
                consumer_id="retired-consumer",
                status=SubscriptionStatus.RETIRED,
            )
        )

    assert factory.calls == 0
    assert connection.commits == 0
    assert connection.rollbacks == 0
    assert connection.closes == 0


def test_subscription_definition_excludes_lifecycle_state_and_timestamps() -> None:
    from framework.events.runtime import DurableSubscription, SubscriptionStatus
    from infrastructure.storage.events.postgres import _subscription_definition

    subscription = DurableSubscription(
        subscription_id="subscription-a",
        subscription_version=1,
        consumer_id="consumer-a",
    )
    created_at = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    lifecycle_update = replace(
        subscription,
        status=SubscriptionStatus.PAUSED,
        created_at=created_at,
        updated_at=created_at + timedelta(minutes=5),
    )

    assert _subscription_definition(lifecycle_update) == _subscription_definition(
        subscription
    )
    assert _subscription_definition(
        replace(subscription, consumer_id="consumer-b")
    ) != _subscription_definition(subscription)


def test_unit_of_work_acquires_only_on_enter_and_unentered_operations_fail_typed() -> None:
    connection = _LifecycleConnection()
    factory = _LifecycleFactory(connection)
    unit_of_work = _store(factory).unit_of_work()

    assert factory.calls == 0
    for operation in (
        lambda: unit_of_work.connection,
        lambda: unit_of_work.append_event(None),  # type: ignore[arg-type]
        lambda: unit_of_work.settle_delivery(None),  # type: ignore[arg-type]
        unit_of_work.commit,
        unit_of_work.rollback,
    ):
        with pytest.raises(EventStoreError, match="has not been entered"):
            operation()
    assert factory.calls == 0
    assert connection.closes == 0


def test_unit_of_work_commit_closes_exactly_once_and_exit_is_idempotent() -> None:
    connection = _LifecycleConnection()
    factory = _LifecycleFactory(connection)
    unit_of_work = _store(factory).unit_of_work()

    with unit_of_work:
        assert unit_of_work.connection is connection
        unit_of_work.commit()

    assert factory.calls == 1
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closes == 1
    with pytest.raises(EventStoreError, match="already closed"):
        unit_of_work.commit()


def test_unit_of_work_rollback_and_implicit_exit_each_close_exactly_once() -> None:
    explicit_connection = _LifecycleConnection()
    explicit = _store(_LifecycleFactory(explicit_connection)).unit_of_work()
    with explicit:
        explicit.rollback()
    assert explicit_connection.commits == 0
    assert explicit_connection.rollbacks == 1
    assert explicit_connection.closes == 1

    implicit_connection = _LifecycleConnection()
    implicit = _store(_LifecycleFactory(implicit_connection)).unit_of_work()
    with implicit:
        pass
    assert implicit_connection.commits == 0
    assert implicit_connection.rollbacks == 1
    assert implicit_connection.closes == 1


def test_unit_of_work_acquire_failure_closes_partially_acquired_connection() -> None:
    connection = _AcquireFailureConnection()
    factory = _LifecycleFactory(connection)
    unit_of_work = _store(factory).unit_of_work()

    with pytest.raises(EventStoreUnavailableError):
        unit_of_work.__enter__()

    assert factory.calls == 1
    assert connection.closes == 1


def test_unit_of_work_rollback_failure_is_typed_closed_and_redacted() -> None:
    connection = _LifecycleConnection(
        rollback_error=psycopg.OperationalError(
            "rollback failed for postgresql://admin:raw-secret@example/test"
        )
    )
    unit_of_work = _store(_LifecycleFactory(connection)).unit_of_work()

    unit_of_work.__enter__()
    with pytest.raises(EventStoreUnavailableError) as failure:
        unit_of_work.rollback()

    assert "raw-secret" not in str(failure.value)
    assert connection.rollbacks == 1
    assert connection.closes == 1


def test_unit_of_work_body_failure_is_not_masked_by_rollback_failure() -> None:
    connection = _LifecycleConnection(
        rollback_error=psycopg.OperationalError("rollback unavailable")
    )
    unit_of_work = _store(_LifecycleFactory(connection)).unit_of_work()

    with pytest.raises(RuntimeError, match="body failed"):
        with unit_of_work:
            raise RuntimeError("body failed")

    assert connection.rollbacks == 1
    assert connection.closes == 1


def test_failed_mutation_marks_unit_of_work_rollback_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _LifecycleConnection()
    store = _store(_LifecycleFactory(connection))
    unit_of_work = store.unit_of_work()

    def fail_append(
        _connection: object,
        _event: object,
        *,
        expected_last_sequence: int | None,
        lock_scope: object,
    ) -> object:
        assert expected_last_sequence is None
        assert lock_scope is not None
        raise ValueError("candidate rejected after transaction work")

    monkeypatch.setattr(store, "_append_event_in_transaction", fail_append)

    unit_of_work.__enter__()
    with pytest.raises(ValueError, match="candidate rejected"):
        unit_of_work.append_event(None)  # type: ignore[arg-type]
    with pytest.raises(EventStoreError, match="rollback-only"):
        unit_of_work.commit()

    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closes == 1


def test_transaction_lock_tracker_is_reentrant_and_upgrades_without_waiting() -> None:
    from infrastructure.storage.events.postgres import (
        _PostgresTransactionLockTracker,
    )

    cursor = _AdvisoryCursor(True, False)
    tracker = _PostgresTransactionLockTracker()
    first = tracker.new_operation()

    first.acquire(cursor, "logical-a", exclusive=False)
    first.acquire(cursor, "logical-a", exclusive=False)
    first.acquire(cursor, "logical-a", exclusive=True)
    second = tracker.new_operation()
    second.acquire(cursor, "logical-a", exclusive=True)

    assert len(cursor.executed) == 2
    assert "pg_advisory_xact_lock_shared" in cursor.executed[0][0]
    assert "pg_try_advisory_xact_lock" in cursor.executed[1][0]

    with pytest.raises(EventStoreContentionError, match="retry"):
        second.acquire(cursor, "logical-b", exclusive=True)
    assert len(cursor.executed) == 3
    assert "pg_try_advisory_xact_lock" in cursor.executed[2][0]


def test_transaction_lock_tracker_rejects_reverse_capacity_before_sql() -> None:
    from infrastructure.storage.events.postgres import (
        _PostgresTransactionLockTracker,
    )

    tracker = _PostgresTransactionLockTracker()
    first = tracker.new_operation()
    high_key = ("tenant", "subscription-b", 1)
    assert first.new_capacity_keys((high_key,)) == (high_key,)
    first.capacity_key_acquired(high_key)

    with pytest.raises(EventStoreContentionError, match="canonical order"):
        tracker.new_operation().new_capacity_keys(
            (("tenant", "subscription-a", 1),)
        )


@pytest.mark.parametrize(
    "error_type",
    (
        psycopg.errors.SerializationFailure,
        psycopg.errors.DeadlockDetected,
        psycopg.errors.LockNotAvailable,
    ),
)
def test_retryable_postgres_sqlstates_map_to_typed_contention(
    error_type: type[psycopg.Error],
) -> None:
    from infrastructure.storage.events.postgres import _reraise_store_exception

    with pytest.raises(EventStoreContentionError, match="retryable contention"):
        _reraise_store_exception(error_type("concurrent transaction conflict"))


def test_deployed_advisory_lock_names_remain_rolling_upgrade_compatible() -> None:
    from infrastructure.storage.events.postgres import (
        _lock_event_identity,
        _lock_subscription_registry,
        _subscription_identity_lock_name,
    )

    cursor = _AdvisoryCursor()
    _lock_subscription_registry(cursor, "tenant-a", exclusive=False)
    _lock_event_identity(cursor, "event-a")

    assert cursor.executed[0][1] == ("event-subscription-registry:tenant-a",)
    assert cursor.executed[1][1] == ("event:event-a",)
    assert _subscription_identity_lock_name(
        SimpleNamespace(subscription_id="subscription-a", subscription_version=2)
    ) == "subscription:subscription-a:2"
