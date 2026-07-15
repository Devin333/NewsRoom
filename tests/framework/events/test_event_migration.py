from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

import pytest

from framework.events.migration import (
    EventMigrationDryRun,
    MigrationClassification,
    MigrationSourceKind,
    MigrationSourceRecord,
)
from framework.events.canonical import (
    BusinessContext,
    EventCandidate,
    ProducerIdentity,
    StoredEvent,
)
from framework.shared.json import stable_json_dumps
from framework.workflow.checkpoint.checksum import attach_checkpoint_checksum
from framework.workflow.checkpoint.envelope import (
    WorkflowCheckpointEnvelope,
    envelope_to_payload,
)


def _record(
    *,
    event_id: str = "evt-1",
    payload: dict | None = None,
    occurred_at: str | None = "2026-07-15T01:00:00Z",
    schema_version: str = "newsroom.event_record.v1",
) -> MigrationSourceRecord:
    value = {
        "event_id": event_id,
        "event_type": "workflow_started",
        "run_id": "run-1",
        "payload": payload or {"run_id": "run-1"},
        "schema_version": schema_version,
    }
    if occurred_at is not None:
        value["occurred_at"] = occurred_at
    return MigrationSourceRecord(
        source_kind=MigrationSourceKind.LEGACY_RUN_JSONL,
        location="events.jsonl:1",
        value=value,
    )


def test_migration_classifies_identical_and_conflicting_event_ids() -> None:
    report = EventMigrationDryRun().scan(
        [
            _record(payload={"run_id": "run-1", "attempt": 1}),
            _record(payload={"run_id": "run-1", "attempt": 1}),
            _record(payload={"run_id": "run-1", "attempt": 2}),
        ]
    )

    assert [finding.classification for finding in report.findings] == [
        MigrationClassification.IMPORTABLE,
        MigrationClassification.DUPLICATE,
        MigrationClassification.CONFLICTING,
    ]
    assert report.counts == {
        "scanned": 3,
        "importable": 1,
        "duplicate": 1,
        "conflicting": 1,
        "unknown_schema": 0,
        "missing_time": 0,
        "quarantined": 0,
        "quarantine_total": 1,
    }


def test_migration_reports_unknown_schema_missing_time_and_general_quarantine() -> None:
    report = EventMigrationDryRun().scan(
        [
            _record(schema_version="newsroom.event_record.v999"),
            _record(event_id="evt-2", occurred_at=None),
            MigrationSourceRecord.issue(
                MigrationSourceKind.LEGACY_RUN_JSONL,
                "events.jsonl:3",
                "invalid_json",
            ),
        ]
    )

    assert [finding.classification for finding in report.findings] == [
        MigrationClassification.UNKNOWN_SCHEMA,
        MigrationClassification.MISSING_TIME,
        MigrationClassification.QUARANTINED,
    ]
    assert report.counts["unknown_schema"] == 1
    assert report.counts["missing_time"] == 1
    assert report.counts["quarantined"] == 1
    assert report.counts["quarantine_total"] == 3


def test_migration_fail_fast_stops_after_quarantine() -> None:
    report = EventMigrationDryRun().scan(
        [
            MigrationSourceRecord.issue(
                MigrationSourceKind.LOCAL_EVENT_RECORD,
                "records.jsonl:1",
                "invalid_json",
            ),
            _record(event_id="never-scanned"),
        ],
        fail_fast=True,
    )

    assert report.halted is True
    assert report.counts["scanned"] == 1


def test_migration_report_never_contains_secret_payload_values() -> None:
    secret = "secret-that-must-not-leak"
    report = EventMigrationDryRun().scan(
        [
            MigrationSourceRecord(
                source_kind=MigrationSourceKind.LOCAL_EVENT_RECORD,
                location="records.jsonl:1",
                value={
                    "event_id": "evt-secret",
                    "event_type": "tool_called",
                    "run_id": "run-1",
                    "occurred_at": "2026-07-15T01:00:00Z",
                    "schema_version": "newsroom.event_record.v1",
                    "payload": {"api_key": secret},
                },
            )
        ]
    )

    serialized = str(report.to_dict())
    assert report.counts["quarantined"] == 1
    assert secret not in serialized
    assert "api_key" not in serialized


def test_migration_rejects_canonical_record_changed_by_current_security_policy() -> None:
    candidate = EventCandidate(
        event_id="evt-canonical-secret",
        event_type="gate_evaluated",
        data_schema="newsroom.harness-event/v1",
        source="workflow",
        occurred_at=datetime(2026, 7, 15, 1, 0, tzinfo=UTC),
        stream_id="run:run-1",
        business_context=BusinessContext(run_id="run-1"),
        producer=ProducerIdentity(component="workflow"),
        payload={
            "gate": "quality",
            "passed": False,
            "details": {"reason": "must-not-leak"},
        },
    )

    report = EventMigrationDryRun().scan(
        [
            MigrationSourceRecord(
                source_kind=MigrationSourceKind.POSTGRESQL_ROW,
                location="postgresql:durable_events:evt-canonical-secret",
                value=candidate.to_dict(),
            )
        ]
    )

    assert report.findings[0].reason == "security_policy_violation"
    assert "must-not-leak" not in str(report.to_dict())


def test_migration_rejects_non_boolean_trace_flag_and_envelope_event_id_conflict() -> None:
    non_boolean_trace = _record().value
    assert non_boolean_trace is not None
    non_boolean_trace = dict(non_boolean_trace)
    non_boolean_trace.update({"trace_id": "1" * 32, "span_id": "2" * 16, "is_remote": "false"})
    conflicting_envelope = {
        "schema_version": "newsroom.event_envelope.v1",
        "event_id": "evt-outer",
        "event": {
            "schema_version": "newsroom.event.v1",
            "event_id": "evt-inner",
            "event_type": "workflow_started",
            "created_at": "2026-07-15T01:00:00Z",
            "run_id": "run-1",
            "payload": {"run_id": "run-1"},
        },
    }

    report = EventMigrationDryRun().scan(
        [
            MigrationSourceRecord(
                MigrationSourceKind.LEGACY_RUN_JSONL,
                "events.jsonl:1",
                non_boolean_trace,
            ),
            MigrationSourceRecord(
                MigrationSourceKind.LEGACY_RUN_JSONL,
                "events.jsonl:2",
                conflicting_envelope,
            ),
        ]
    )

    assert [finding.reason for finding in report.findings] == [
        "unsupported_legacy_mapping",
        "context_conflict",
    ]


def test_fail_fast_closes_source_iterator() -> None:
    closed = False

    def records():
        nonlocal closed
        try:
            yield MigrationSourceRecord.issue(
                MigrationSourceKind.POSTGRESQL_ROW,
                "postgresql:workflow_events:run-1:0",
                "invalid_json",
            )
            yield _record(event_id="never-scanned")
        finally:
            closed = True

    EventMigrationDryRun().scan(records(), fail_fast=True)

    assert closed is True


def test_migration_quarantines_naive_historical_occurrence_time() -> None:
    report = EventMigrationDryRun().scan(
        [_record(occurred_at="2026-07-15T01:00:00")]
    )

    assert report.findings[0].reason == "invalid_occurred_at"


def test_migration_counts_are_exclusive_and_expose_quarantine_total() -> None:
    report = EventMigrationDryRun().scan(
        [
            _record(),
            _record(),
            _record(payload={"run_id": "run-1", "topic": "changed"}),
            _record(event_id="unknown", schema_version="newsroom.event_record.v999"),
            _record(event_id="missing", occurred_at=None),
            MigrationSourceRecord.issue(
                MigrationSourceKind.LEGACY_RUN_JSONL,
                "events.jsonl:6",
                "invalid_json",
            ),
        ]
    )

    counts = report.counts
    exclusive_total = sum(
        counts[name]
        for name in (
            "importable",
            "duplicate",
            "conflicting",
            "unknown_schema",
            "missing_time",
            "quarantined",
        )
    )
    assert exclusive_total == counts["scanned"]
    assert counts["quarantine_total"] == 4


def test_migration_uses_relocation_stable_source_identity_for_missing_event_id() -> None:
    def record(location: str, *, topic: str = "same") -> MigrationSourceRecord:
        return MigrationSourceRecord(
            source_kind=MigrationSourceKind.LEGACY_RUN_JSONL,
            location=location,
            value={
                "event_type": "workflow_started",
                "run_id": "run-source-identity",
                "occurred_at": "2026-07-15T01:00:00Z",
                "payload": {"run_id": "run-source-identity", "topic": topic},
            },
        )

    report = EventMigrationDryRun().scan(
        [
            record(r"C:\\old-root\\events.jsonl:1"),
            record(r"D:\\moved-root\\events.jsonl:1"),
            record(r"D:\\moved-root\\other-events.jsonl:1"),
            record(r"D:\\moved-root\\events.jsonl:2"),
            record(r"C:\\old-root\\events.jsonl:1", topic="changed"),
        ]
    )

    assert [finding.classification for finding in report.findings] == [
        MigrationClassification.IMPORTABLE,
        MigrationClassification.DUPLICATE,
        MigrationClassification.IMPORTABLE,
        MigrationClassification.IMPORTABLE,
        MigrationClassification.CONFLICTING,
    ]
    assert report.findings[0].event_id == report.findings[1].event_id
    assert report.findings[0].event_id != report.findings[2].event_id
    assert report.findings[0].event_id != report.findings[3].event_id


@pytest.mark.parametrize("field_name", ["correlation_id", "causation_id", "tenant_id"])
def test_migration_quarantines_all_authoritative_envelope_conflicts(
    field_name: str,
) -> None:
    value = {
        "schema_version": "newsroom.event_envelope.v1",
        "event_id": "evt-context-conflict",
        field_name: "outer-value",
        "event": {
            "schema_version": "newsroom.event.v1",
            "event_id": "evt-context-conflict",
            "event_type": "workflow_started",
            "created_at": "2026-07-15T01:00:00Z",
            "run_id": "run-1",
            field_name: "inner-value",
            "payload": {"run_id": "run-1"},
        },
    }

    report = EventMigrationDryRun().scan(
        [
            MigrationSourceRecord(
                MigrationSourceKind.LEGACY_RUN_JSONL,
                "events.jsonl:1",
                value,
            )
        ]
    )

    assert report.findings[0].classification is MigrationClassification.CONFLICTING
    assert report.findings[0].reason == "context_conflict"


def test_migration_preserves_nonempty_inner_event_id_when_outer_id_is_empty() -> None:
    value = {
        "schema_version": "newsroom.event_envelope.v1",
        "event_id": None,
        "event": {
            "schema_version": "newsroom.event.v1",
            "event_id": "evt-inner-authority",
            "event_type": "workflow_started",
            "created_at": "2026-07-15T01:00:00Z",
            "run_id": "run-1",
            "payload": {"run_id": "run-1"},
        },
    }

    report = EventMigrationDryRun().scan(
        [MigrationSourceRecord(MigrationSourceKind.LEGACY_RUN_JSONL, "events.jsonl:1", value)]
    )

    assert report.findings[0].event_id == "evt-inner-authority"
    assert report.findings[0].classification is MigrationClassification.IMPORTABLE


def test_migration_classifies_missing_time_for_canonical_record() -> None:
    candidate = EventCandidate(
        event_id="evt-canonical-missing-time",
        event_type="workflow_started",
        data_schema="newsroom.workflow-event/v1",
        source="workflow",
        occurred_at=datetime(2026, 7, 15, 1, 0, tzinfo=UTC),
        stream_id="run:run-1",
        business_context=BusinessContext(run_id="run-1"),
        producer=ProducerIdentity(component="workflow"),
        payload={"run_id": "run-1"},
    ).to_dict()
    candidate.pop("occurred_at")

    report = EventMigrationDryRun().scan(
        [
            MigrationSourceRecord(
                MigrationSourceKind.LOCAL_EVENT_RECORD,
                "events.jsonl:1",
                candidate,
            )
        ]
    )

    assert report.findings[0].classification is MigrationClassification.MISSING_TIME


def test_migration_does_not_invent_timezone_for_canonical_observation_time() -> None:
    candidate = EventCandidate(
        event_id="evt-canonical-naive-observed",
        event_type="workflow_started",
        data_schema="newsroom.workflow-event/v1",
        source="workflow",
        occurred_at=datetime(2026, 7, 15, 1, 0, tzinfo=UTC),
        stream_id="run:run-1",
        business_context=BusinessContext(run_id="run-1"),
        producer=ProducerIdentity(component="workflow"),
        payload={"run_id": "run-1"},
    )
    stored = StoredEvent(
        candidate=candidate,
        observed_at=datetime(2026, 7, 15, 1, 1, tzinfo=UTC),
        stream_sequence=1,
    ).to_dict()
    stored["observed_at"] = "2026-07-15T01:01:00"

    report = EventMigrationDryRun().scan(
        [
            MigrationSourceRecord(
                MigrationSourceKind.POSTGRESQL_ROW,
                "postgresql:durable_events:evt-canonical-naive-observed",
                stored,
            )
        ]
    )

    assert report.findings[0].reason == "invalid_observed_at"


def test_migration_accepts_current_workflow_checkpoint_and_detects_state_conflict() -> None:
    first = _workflow_checkpoint_payload(buffer_value="first")
    second = _workflow_checkpoint_payload(buffer_value="second")

    report = EventMigrationDryRun().scan(
        [
            MigrationSourceRecord(MigrationSourceKind.CHECKPOINT, "checkpoint-a.json", first),
            MigrationSourceRecord(MigrationSourceKind.CHECKPOINT, "checkpoint-b.json", second),
        ]
    )

    assert [finding.classification for finding in report.findings] == [
        MigrationClassification.IMPORTABLE,
        MigrationClassification.CONFLICTING,
    ]


def test_migration_validates_workflow_checksum_when_schema_is_nested_in_payload() -> None:
    valid = _workflow_checkpoint_payload(buffer_value="nested-valid")
    corrupt = dict(valid)
    corrupt["checksum"] = "0" * 64

    report = EventMigrationDryRun().scan(
        [
            MigrationSourceRecord(
                MigrationSourceKind.CHECKPOINT,
                "nested-valid.json",
                {"payload": valid},
            ),
            MigrationSourceRecord(
                MigrationSourceKind.CHECKPOINT,
                "nested-corrupt.json",
                {"payload": corrupt},
            ),
        ]
    )

    assert report.findings[0].classification is MigrationClassification.IMPORTABLE
    assert report.findings[1].classification is MigrationClassification.QUARANTINED
    assert report.findings[1].reason == "checkpoint_checksum_mismatch"


def test_migration_verifies_current_checkpoint_saved_model_shape() -> None:
    envelope = _workflow_checkpoint_payload(buffer_value="saved-model")
    metadata = dict(envelope["metadata"])
    event_offset = metadata.pop("event_offset")
    metadata["runtime_only"] = {
        "checkpoint_envelope": {
            "schema_version": envelope["schema_version"],
            "manifest_hash": envelope["manifest_hash"],
            "checksum": envelope["checksum"],
        }
    }
    saved_model = {
        key: value
        for key, value in envelope.items()
        if key not in {"schema_version", "manifest_hash", "checksum", "metadata"}
    }
    saved_model.update({"event_offset": event_offset, "metadata": metadata})
    corrupt = dict(saved_model)
    corrupt["data_buffer_snapshot"] = {"value": "tampered"}

    report = EventMigrationDryRun().scan(
        [
            MigrationSourceRecord(MigrationSourceKind.CHECKPOINT, "saved.json", saved_model),
            MigrationSourceRecord(MigrationSourceKind.CHECKPOINT, "corrupt.json", corrupt),
        ]
    )

    assert report.findings[0].classification is MigrationClassification.IMPORTABLE
    assert report.findings[1].reason == "checkpoint_checksum_mismatch"


def test_migration_validates_harness_checkpoint_checksum_and_complete_state() -> None:
    first = _harness_checkpoint_payload(status="running")
    second = _harness_checkpoint_payload(status="succeeded")
    corrupt = dict(first)
    corrupt["checkpoint_id"] = "cp-harness-corrupt"
    corrupt["state"] = {"status": "corrupt", "attempt": 1}

    report = EventMigrationDryRun().scan(
        [
            MigrationSourceRecord(MigrationSourceKind.CHECKPOINT, "harness-a.json", first),
            MigrationSourceRecord(MigrationSourceKind.CHECKPOINT, "harness-b.json", second),
            MigrationSourceRecord(MigrationSourceKind.CHECKPOINT, "harness-c.json", corrupt),
        ]
    )

    assert [finding.classification for finding in report.findings] == [
        MigrationClassification.IMPORTABLE,
        MigrationClassification.CONFLICTING,
        MigrationClassification.QUARANTINED,
    ]
    assert report.findings[2].reason == "checkpoint_checksum_mismatch"


def test_event_and_checkpoint_identity_namespaces_cannot_false_collide() -> None:
    report = EventMigrationDryRun().scan(
        [
            _record(event_id="checkpoint:run-1:cp-1"),
            MigrationSourceRecord(
                MigrationSourceKind.CHECKPOINT,
                "checkpoint.json",
                {"checkpoint_id": "cp-1", "run_id": "run-1", "event_offset": 0},
            ),
        ]
    )

    assert [finding.classification for finding in report.findings] == [
        MigrationClassification.IMPORTABLE,
        MigrationClassification.IMPORTABLE,
    ]


def _workflow_checkpoint_payload(*, buffer_value: str) -> dict:
    envelope = WorkflowCheckpointEnvelope(
        checkpoint_id="cp-workflow-current",
        schema_version="workflow-checkpoint/v1",
        run_id="run-checkpoint",
        workflow_id="workflow-checkpoint",
        workflow_version="1.0.0",
        current_step_ids=["collect"],
        data_buffer_snapshot={"value": buffer_value},
        step_results={},
        path=["collect"],
        manifest_hash=None,
        checksum="pending",
        created_at="2026-07-15T01:00:00Z",
        metadata={"event_offset": 3, "protected": {"owner": "runtime"}},
    )
    return envelope_to_payload(attach_checkpoint_checksum(envelope))


def _harness_checkpoint_payload(*, status: str) -> dict:
    payload = {
        "checkpoint_id": "cp-harness-current",
        "run_id": "run-checkpoint",
        "state": {"status": status, "attempt": 1},
        "last_event_id": "evt-last",
        "artifact_refs": [],
        "metadata": {},
        "created_at": "2026-07-15T01:00:00Z",
    }
    checksum_payload = {
        "run_id": payload["run_id"],
        "state": payload["state"],
        "last_event_id": payload["last_event_id"],
    }
    payload["checksum"] = "sha256:" + sha256(
        stable_json_dumps(checksum_payload).encode("utf-8")
    ).hexdigest()
    return payload
