from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from framework.events.errors import (
    EventStoreCapacityError,
    EventStoreContentionError,
    EventStoreCorruptionError,
    EventStoreUnavailableError,
)
from framework.events.runtime.activities import (
    ActivityRecorder,
    RecordedActivityResolver,
    ReplayActivityHandlerVersion,
    ReplayActivityKind,
    ReplayActivityRecordingConflictError,
    ReplayActivityRegistry,
    ReplayActivityStatus,
)
from framework.events.schema.security import SecurityClassification
from framework.harness import HarnessActivity, HarnessWorkerResult
from framework.harness.control_plane.activity import HarnessActivityResultRecord


ACCEPTED_AT = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
STARTED_AT = ACCEPTED_AT + timedelta(seconds=1)
COMPLETED_AT = STARTED_AT + timedelta(seconds=2)


@pytest.fixture(scope="module")
def postgres_dsn() -> str:
    if os.getenv("NEWSROOM_RUN_POSTGRES_EVENT_INTEGRATION") != "1":
        pytest.skip(
            "real PostgreSQL recorded-activity integration is an explicit gate; "
            "set NEWSROOM_RUN_POSTGRES_EVENT_INTEGRATION=1"
        )
    dsn = os.getenv("NEWS_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.fail("NEWS_TEST_POSTGRES_DSN is required for the real PostgreSQL gate")

    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    if "test" not in str(conninfo_to_dict(dsn).get("dbname") or "").casefold():
        pytest.fail("NEWS_TEST_POSTGRES_DSN must select a database containing 'test'")
    migration = (
        Path(__file__).resolve().parents[4]
        / "infrastructure"
        / "storage"
        / "postgres"
        / "migrations"
        / "009_recorded_activities.sql"
    )
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration.read_text(encoding="utf-8"))
        connection.commit()
    return dsn


@pytest.fixture
def scope(postgres_dsn: str) -> str:
    value = f"pg-activity:{uuid4().hex}"
    yield value
    _cleanup(postgres_dsn, value)


def test_real_postgres_records_encrypted_payloads_and_resolves_after_restart(
    postgres_dsn: str,
    scope: str,
) -> None:
    from infrastructure.storage.events.activity_store import (
        PostgresRecordedActivityStore,
    )

    key = Fernet.generate_key()
    tenant_id = f"{scope}:tenant"
    activity_id = f"{scope}:recorded"
    store = PostgresRecordedActivityStore(postgres_dsn, encryption_key=key)
    completed = _accept(store, activity_id, tenant_id).succeed(
        {"answer": "postgres-secret-output"},
        completed_at=COMPLETED_AT,
    )
    restarted = PostgresRecordedActivityStore(postgres_dsn, encryption_key=key)
    registry = ReplayActivityRegistry()
    registry.register(
        ReplayActivityHandlerVersion(
            ReplayActivityKind.LLM,
            "newsroom.activity/v1",
            "llm-provider/2",
        )
    )

    resolved = RecordedActivityResolver(restarted, registry).resolve(
        completed.record.activity,
        completed.recorded_ref,
    )

    assert restarted.validate_reference(
        completed.recorded_ref.to_dict(),
        tenant_id=tenant_id,
        classification=SecurityClassification.CONFIDENTIAL,
    ).complete
    assert resolved.outcome.status is ReplayActivityStatus.SUCCEEDED
    assert resolved.outcome.output_ref is not None
    assert resolved.outcome.output_ref.uri != completed.recorded_ref.uri
    assert restarted.get_payload(
        resolved.outcome.output_ref,
        tenant_id=tenant_id,
    ) == {"answer": "postgres-secret-output"}
    ciphertexts = _ciphertexts(postgres_dsn, activity_id, tenant_id)
    assert len(ciphertexts) == 3
    assert all(b"postgres-secret-input" not in value for value in ciphertexts)
    assert all(b"postgres-secret-output" not in value for value in ciphertexts)
    assert {
        (entry["object_role"], entry["operation"])
        for entry in restarted.access_audit(activity_id, tenant_id=tenant_id)
    } >= {
        ("input", "write"),
        ("output", "write"),
        ("record", "write"),
        ("record", "read"),
        ("output", "read"),
    }


def test_real_postgres_concurrent_exact_retries_commit_one_terminal_record(
    postgres_dsn: str,
    scope: str,
) -> None:
    from infrastructure.storage.events.activity_store import (
        PostgresRecordedActivityStore,
    )

    store = PostgresRecordedActivityStore(
        postgres_dsn,
        encryption_key=Fernet.generate_key(),
    )
    tenant_id = f"{scope}:tenant"
    activity_id = f"{scope}:concurrent"

    with ThreadPoolExecutor(max_workers=12) as executor:
        accepted = list(
            executor.map(
                lambda _index: _accept(store, activity_id, tenant_id),
                range(24),
            )
        )

    assert len({handle.recorded_ref for handle in accepted}) == 1
    with ThreadPoolExecutor(max_workers=12) as executor:
        completed = list(
            executor.map(
                lambda handle: handle.succeed(
                    {"answer": "same-output"},
                    completed_at=COMPLETED_AT,
                ),
                accepted,
            )
        )

    assert len({write.recorded_ref for write in completed}) == 1
    with pytest.raises(ReplayActivityRecordingConflictError):
        _accept(store, activity_id, tenant_id).fail(
            "provider_timeout",
            {"reason": "different-terminal-outcome"},
            completed_at=COMPLETED_AT,
        )
    assert _row_counts(postgres_dsn, activity_id, tenant_id) == (1, 2)
    audit = store.access_audit(activity_id, tenant_id=tenant_id)
    assert sum(
        entry["object_role"] == "input" and entry["operation"] == "write"
        for entry in audit
    ) == 1
    assert any(
        entry["object_role"] == "input" and entry["operation"] == "read"
        for entry in audit
    )
    assert sum(
        entry["object_role"] == "output" and entry["operation"] == "write"
        for entry in audit
    ) == 1


def test_real_postgres_isolates_same_activity_identity_by_tenant(
    postgres_dsn: str,
    scope: str,
) -> None:
    from infrastructure.storage.events.activity_store import (
        PostgresRecordedActivityStore,
    )

    store = PostgresRecordedActivityStore(
        postgres_dsn,
        encryption_key=Fernet.generate_key(),
    )
    activity_id = f"{scope}:shared-identity"
    tenant_a = f"{scope}:tenant-a"
    tenant_b = f"{scope}:tenant-b"

    write_a = _accept(store, activity_id, tenant_a).succeed(
        {"answer": "tenant-a"},
        completed_at=COMPLETED_AT,
    )
    write_b = _accept(store, activity_id, tenant_b).succeed(
        {"answer": "tenant-b"},
        completed_at=COMPLETED_AT,
    )

    assert write_a.recorded_ref != write_b.recorded_ref
    assert _row_counts(postgres_dsn, activity_id, tenant_a) == (1, 2)
    assert _row_counts(postgres_dsn, activity_id, tenant_b) == (1, 2)
    with pytest.raises(ReplayActivityRecordingConflictError, match="tenant"):
        store.get_record(write_a.recorded_ref, tenant_id=tenant_b)
    assert store.access_audit(activity_id, tenant_id=tenant_a)
    assert store.access_audit(activity_id, tenant_id=tenant_b)


def test_real_postgres_rejects_cross_tenant_and_detects_tampering(
    postgres_dsn: str,
    scope: str,
) -> None:
    import psycopg

    from infrastructure.storage.events.activity_store import (
        PostgresRecordedActivityStore,
    )

    tenant_id = f"{scope}:tenant"
    activity_id = f"{scope}:tampered"
    store = PostgresRecordedActivityStore(
        postgres_dsn,
        encryption_key=Fernet.generate_key(),
    )
    write = _accept(store, activity_id, tenant_id).succeed(
        {"answer": "recorded"},
        completed_at=COMPLETED_AT,
    )

    with pytest.raises(ReplayActivityRecordingConflictError, match="tenant"):
        store.get_record(write.recorded_ref, tenant_id=f"{scope}:other-tenant")

    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE event_activity_records SET ciphertext = %s "
                "WHERE tenant_scope = %s AND activity_id = %s",
                (b"tampered", tenant_id, activity_id),
            )
        connection.commit()

    with pytest.raises(EventStoreCorruptionError, match="ciphertext"):
        store.get_record(write.recorded_ref, tenant_id=tenant_id)


def test_real_postgres_implements_secure_harness_result_contract(
    postgres_dsn: str,
    scope: str,
) -> None:
    from infrastructure.storage.events.activity_store import (
        PostgresRecordedActivityStore,
    )

    tenant_id = f"{scope}:tenant"
    store = PostgresRecordedActivityStore(
        postgres_dsn,
        encryption_key=Fernet.generate_key(),
    )
    activity = HarnessActivity.for_worker_call(
        run_id=f"{scope}:run",
        step_id="collect",
        attempt=1,
        activity_type="llm",
        inputs={"prompt": "postgres-harness-input"},
    )
    record = HarnessActivityResultRecord(
        activity=activity,
        result=HarnessWorkerResult(
            status="succeeded",
            output={"answer": "postgres-harness-output"},
        ),
        accepted_at=ACCEPTED_AT,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    reference = store.put_result(
        record,
        tenant_id=tenant_id,
        classification=SecurityClassification.CONFIDENTIAL,
    )

    assert store.validate_reference(
        reference.to_dict(),
        tenant_id=tenant_id,
        classification=SecurityClassification.CONFIDENTIAL,
    ).complete
    assert (
        store.resolve_result(
            reference,
            tenant_id=tenant_id,
            classification=SecurityClassification.CONFIDENTIAL,
        )
        == record
    )
    assert (
        store.put_result(
            record,
            tenant_id=tenant_id,
            classification=SecurityClassification.CONFIDENTIAL,
        )
        == reference
    )
    ciphertexts = _ciphertexts(postgres_dsn, activity.activity_id, tenant_id)
    assert len(ciphertexts) == 1
    assert b"postgres-harness-input" not in ciphertexts[0]
    assert b"postgres-harness-output" not in ciphertexts[0]
    assert {
        (entry["object_role"], entry["operation"])
        for entry in store.access_audit(
            activity.activity_id,
            tenant_id=tenant_id,
        )
    } >= {("record", "write"), ("record", "read")}


@pytest.mark.parametrize(
    ("sqlstate", "expected_error"),
    [
        ("40001", EventStoreContentionError),
        ("53100", EventStoreCapacityError),
        ("08006", EventStoreUnavailableError),
        ("23514", EventStoreCorruptionError),
    ],
)
def test_postgres_activity_store_maps_database_failures(
    sqlstate: str,
    expected_error: type[Exception],
) -> None:
    import psycopg

    from infrastructure.storage.events.activity_store import (
        PostgresRecordedActivityStore,
    )

    database_error = type(
        f"PostgresFailure{sqlstate}",
        (psycopg.DatabaseError,),
        {"sqlstate": sqlstate},
    )

    def fail_connection():
        raise database_error("injected PostgreSQL failure")

    store = PostgresRecordedActivityStore(
        "postgresql://localhost/newsroom_test",
        encryption_key=Fernet.generate_key(),
        connection_factory=fail_connection,
    )

    with pytest.raises(expected_error):
        store.access_audit("activity", tenant_id=None)


def _accept(store, activity_id: str, tenant_id: str):
    return ActivityRecorder(store).accept(
        activity_id=activity_id,
        activity_kind=ReplayActivityKind.LLM,
        input_value={"prompt": "postgres-secret-input"},
        idempotency_key=f"{activity_id}:idempotency",
        attempt=1,
        contract_version="newsroom.activity/v1",
        handler_version="llm-provider/2",
        accepted_at=ACCEPTED_AT,
        started_at=STARTED_AT,
        tenant_id=tenant_id,
        security_classification=SecurityClassification.CONFIDENTIAL,
    )


def _row_counts(dsn: str, activity_id: str, tenant_id: str) -> tuple[int, int]:
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM event_activity_records "
                "WHERE tenant_scope = %s AND activity_id = %s",
                (tenant_id, activity_id),
            )
            records = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT count(*) FROM event_activity_payloads "
                "WHERE tenant_scope = %s AND activity_id = %s",
                (tenant_id, activity_id),
            )
            payloads = int(cursor.fetchone()[0])
    return records, payloads


def _ciphertexts(dsn: str, activity_id: str, tenant_id: str) -> tuple[bytes, ...]:
    import psycopg

    values: list[bytes] = []
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            for table in (
                "event_activity_payloads",
                "event_activity_records",
                "harness_activity_results",
            ):
                cursor.execute(
                    f"SELECT ciphertext FROM {table} "
                    "WHERE tenant_scope = %s AND activity_id = %s",
                    (tenant_id, activity_id),
                )
                values.extend(bytes(row[0]) for row in cursor.fetchall())
    return tuple(values)


def _cleanup(dsn: str, scope: str) -> None:
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            for table in (
                "event_activity_access_audit",
                "event_activity_records",
                "event_activity_payloads",
                "harness_activity_results",
            ):
                cursor.execute(
                    f"DELETE FROM {table} WHERE activity_id LIKE %s",
                    (f"{scope}:%",),
                )
        connection.commit()
