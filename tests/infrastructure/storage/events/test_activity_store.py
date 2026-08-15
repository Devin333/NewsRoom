from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet

from framework.events.errors import EventStoreCorruptionError
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
from framework.harness import (
    HarnessControlPlane,
    HarnessRunSpec,
    HarnessStepSpec,
)
from framework.harness.workflow.spec import HarnessWorkflowSpec
from framework.harness.control_plane.activity import HarnessActivityResultRecord
from infrastructure.storage.events.activity_store import SQLiteRecordedActivityStore
from infrastructure.storage.events.factory import durable_event_storage_from_env


ACCEPTED_AT = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
STARTED_AT = ACCEPTED_AT + timedelta(seconds=1)
COMPLETED_AT = STARTED_AT + timedelta(seconds=2)


def _store(tmp_path, *, key: bytes | None = None) -> SQLiteRecordedActivityStore:
    return SQLiteRecordedActivityStore(
        tmp_path / "events.sqlite3",
        encryption_key=key or Fernet.generate_key(),
    )


def _accept(store: SQLiteRecordedActivityStore):
    return ActivityRecorder(store).accept(
        activity_id="activity-1",
        activity_kind=ReplayActivityKind.LLM,
        input_value={"prompt": "secret-input"},
        idempotency_key="activity:1",
        attempt=1,
        contract_version="newsroom.activity/v1",
        handler_version="llm-provider/2",
        accepted_at=ACCEPTED_AT,
        started_at=STARTED_AT,
        tenant_id="tenant-a",
        security_classification=SecurityClassification.CONFIDENTIAL,
    )


def test_sqlite_activity_store_records_separate_encrypted_payloads_and_resolves(tmp_path) -> None:
    store = _store(tmp_path)
    handle = _accept(store)
    pending_ref = handle.recorded_ref
    completed = handle.succeed(
        {"answer": "secret-output"},
        completed_at=COMPLETED_AT,
    )
    registry = ReplayActivityRegistry()
    registry.register(
        ReplayActivityHandlerVersion(
            ReplayActivityKind.LLM,
            "newsroom.activity/v1",
            "llm-provider/2",
        )
    )

    resolved = RecordedActivityResolver(store, registry).resolve(
        completed.record.activity,
        completed.recorded_ref,
    )

    assert resolved.outcome.status is ReplayActivityStatus.SUCCEEDED
    assert resolved.outcome.output_ref is not None
    assert resolved.outcome.output_ref.uri != completed.recorded_ref.uri
    assert store.get_payload(
        resolved.outcome.output_ref,
        tenant_id="tenant-a",
    ) == {"answer": "secret-output"}
    database_bytes = (tmp_path / "events.sqlite3").read_bytes()
    assert b"secret-input" not in database_bytes
    assert b"secret-output" not in database_bytes
    assert pending_ref != completed.recorded_ref


def test_sqlite_activity_store_exact_retry_is_idempotent_and_conflict_is_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    first = _accept(store)
    second = _accept(store)

    assert second.recorded_ref == first.recorded_ref
    first_write = first.fail(
        "provider_timeout",
        {"reason": "redacted"},
        completed_at=COMPLETED_AT,
    )
    assert first.fail(
        "provider_timeout",
        {"reason": "redacted"},
        completed_at=COMPLETED_AT,
    ) == first_write
    with pytest.raises(ReplayActivityRecordingConflictError):
        second.succeed({"answer": "different"}, completed_at=COMPLETED_AT)


def test_sqlite_activity_store_rejects_cross_tenant_and_tampered_ciphertext(tmp_path) -> None:
    key = Fernet.generate_key()
    store = _store(tmp_path, key=key)
    write = _accept(store).succeed(
        {"answer": "recorded"},
        completed_at=COMPLETED_AT,
    )

    with pytest.raises(ReplayActivityRecordingConflictError, match="tenant"):
        store.get_record(write.recorded_ref, tenant_id="tenant-b")

    with sqlite3.connect(tmp_path / "events.sqlite3") as connection:
        connection.execute(
            "UPDATE event_activity_records SET ciphertext = ? WHERE activity_id = ?",
            (b"tampered", "activity-1"),
        )
        connection.commit()

    with pytest.raises(EventStoreCorruptionError, match="ciphertext"):
        store.get_record(write.recorded_ref, tenant_id="tenant-a")


def test_sqlite_activity_store_records_access_audit(tmp_path) -> None:
    store = _store(tmp_path)
    write = _accept(store).succeed(
        {"answer": "recorded"},
        completed_at=COMPLETED_AT,
    )
    assert store.get_record(write.recorded_ref, tenant_id="tenant-a") is not None

    with sqlite3.connect(tmp_path / "events.sqlite3") as connection:
        rows = connection.execute(
            "SELECT object_role, operation FROM event_activity_access_audit "
            "ORDER BY audit_id"
        ).fetchall()

    assert ("input", "write") in rows
    assert ("output", "write") in rows
    assert ("record", "write") in rows
    assert ("record", "read") in rows


def test_sqlite_activity_store_implements_secure_harness_result_contract(tmp_path) -> None:
    store = _store(tmp_path)
    activity = HarnessActivity.for_worker_call(
        run_id="run-secure",
        step_id="collect",
        attempt=1,
        activity_type="llm",
        inputs={"prompt": "secret-input"},
    )
    record = HarnessActivityResultRecord(
        activity=activity,
        result=HarnessWorkerResult(
            status="succeeded",
            output={"answer": "secret-output"},
        ),
        accepted_at=ACCEPTED_AT,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
    )

    reference = store.put_result(
        record,
        tenant_id="tenant-a",
        classification=SecurityClassification.CONFIDENTIAL,
    )

    validation = store.validate_reference(
        reference.to_dict(),
        tenant_id="tenant-a",
        classification=SecurityClassification.CONFIDENTIAL,
    )
    assert validation.complete is True
    assert store.resolve_result(
        reference,
        tenant_id="tenant-a",
        classification=SecurityClassification.CONFIDENTIAL,
    ) == record
    database_bytes = (tmp_path / "events.sqlite3").read_bytes()
    assert b"secret-input" not in database_bytes
    assert b"secret-output" not in database_bytes


def test_default_composition_runs_harness_with_encrypted_activity_store(tmp_path) -> None:
    key = Fernet.generate_key().decode("ascii")
    composition = durable_event_storage_from_env(
        artifact_root=tmp_path,
        env={"NEWS_ACTIVITY_ENCRYPTION_KEY": key},
    )
    worker_calls = 0

    def worker(_task):
        nonlocal worker_calls
        worker_calls += 1
        return HarnessWorkerResult(
            status="succeeded",
            output={"answer": "composition-secret"},
        )

    result = HarnessControlPlane(
        event_port=composition.create_harness_transition_port(
            tenant_id="tenant-a",
        ),
        worker_registry={"collect": worker},
    ).run(
        HarnessRunSpec(
            run_id="run-composed-activity",
            workflow=HarnessWorkflowSpec(
                workflow_id="composed-activity",
                steps=(HarnessStepSpec(step_id="collect", worker_type="llm"),),
                entry_step_id="collect",
                metadata={"version": "1"},
            ),
        )
    )

    assert result.succeeded is True
    assert worker_calls == 1
    assert b"composition-secret" not in (
        tmp_path / "_records" / "events.sqlite3"
    ).read_bytes()
