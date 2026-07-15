from __future__ import annotations

from typing import Any

import pytest

from framework.events.errors import EventStoreError, EventStoreUnavailableError

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


def _store(factory: _LifecycleFactory) -> Any:
    from infrastructure.storage.events.postgres import PostgresDurableEventStore

    return PostgresDurableEventStore(
        "postgresql://example/test",
        connection_factory=factory,
    )


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
