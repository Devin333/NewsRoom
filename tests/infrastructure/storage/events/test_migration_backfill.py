from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from framework.events.canonical import checksum_for
from framework.events.migration import MigrationSourceKind, MigrationSourceRecord
from framework.events.migration_backfill import (
    EventMigrationBackfill,
    MigrationBackfillReport,
    MigrationBackfillStatus,
    MigrationImportDisposition,
    MigrationResumeError,
    MigrationShadowComparator,
    MigrationShadowReport,
    MigrationSourceChangedError,
    migration_records_fingerprint,
)
from framework.events.schema import default_event_schema_catalog
from framework.workflow.runtime.event_projection import project_workflow_event
from infrastructure.storage.events.migration_reports import (
    JsonMigrationBackfillReportStore,
    read_migration_shadow_report,
    write_migration_shadow_report,
)
from infrastructure.storage.events.sqlite import SQLiteEventStore


NOW = datetime(2026, 7, 16, 1, 0, tzinfo=UTC)
SOURCE_FINGERPRINT = checksum_for({"source": "immutable-fixture"})


def test_backfill_imports_staging_history_and_records_explicit_mappings(
    tmp_path,
) -> None:
    records = (
        _event_record(location="events.jsonl:1"),
        _event_record(location="events.jsonl:2"),
        _checkpoint_record(),
        MigrationSourceRecord.issue(
            MigrationSourceKind.HARNESS_HISTORY,
            "harness.jsonl:1",
            "invalid_json",
        ),
    )
    store, backfill, report_store = _backfill(tmp_path)

    report = backfill.run(
        records,
        report_id="staging-run-1",
        source_fingerprint=SOURCE_FINGERPRINT,
        records_fingerprint=migration_records_fingerprint(records),
        verify_source_fingerprint=lambda: SOURCE_FINGERPRINT,
    )

    assert report.status is MigrationBackfillStatus.SUCCEEDED
    assert report.counts == {
        "imported": 1,
        "duplicate": 1,
        "checkpoint_mapped": 1,
        "quarantined": 1,
        "total": 4,
    }
    assert [entry.disposition for entry in report.entries] == [
        MigrationImportDisposition.IMPORTED,
        MigrationImportDisposition.DUPLICATE,
        MigrationImportDisposition.CHECKPOINT_MAPPED,
        MigrationImportDisposition.QUARANTINED,
    ]
    assert report.entries[0].legacy_offset == 0
    assert report.entries[0].canonical_sequence == 1
    assert report.entries[1].legacy_offset == 1
    assert report.entries[1].canonical_sequence == 1
    assert report.entries[2].legacy_offset == 0
    assert store.get_stream_high_watermark("run:run-1") == 1
    assert report_store.load("staging-run-1") == report


def test_backfill_resumes_per_record_after_runtime_interruption(
    tmp_path,
    monkeypatch,
) -> None:
    records = (
        _event_record(location="events.jsonl:1", event_id="evt-1"),
        _event_record(location="events.jsonl:2", event_id="evt-2"),
    )
    store = SQLiteEventStore(tmp_path / "events.sqlite3", clock=lambda: NOW)
    report_store = JsonMigrationBackfillReportStore(tmp_path / "backfill.json")
    original_unit_of_work = store.unit_of_work
    monkeypatch.setattr(
        store,
        "unit_of_work",
        _FailOnAppendFactory(original_unit_of_work, call_number=2),
    )
    interrupted = EventMigrationBackfill(
        store=store,
        report_store=report_store,
        project_event=_project_event,
        clock=lambda: NOW,
    )

    with pytest.raises(RuntimeError, match="injected migration interruption"):
        interrupted.run(
            records,
            report_id="resume-run",
            source_fingerprint=SOURCE_FINGERPRINT,
            records_fingerprint=migration_records_fingerprint(records),
            verify_source_fingerprint=lambda: SOURCE_FINGERPRINT,
        )

    partial = report_store.load("resume-run")
    assert partial is not None
    assert partial.status is MigrationBackfillStatus.RUNNING
    assert [entry.event_id for entry in partial.entries] == ["evt-1"]

    monkeypatch.setattr(store, "unit_of_work", original_unit_of_work)
    resumed = EventMigrationBackfill(
        store=store,
        report_store=report_store,
        project_event=_project_event,
        clock=lambda: NOW + timedelta(seconds=1),
    ).run(
        records,
        report_id="resume-run",
        source_fingerprint=SOURCE_FINGERPRINT,
        records_fingerprint=migration_records_fingerprint(records),
        verify_source_fingerprint=lambda: SOURCE_FINGERPRINT,
    )

    assert resumed.status is MigrationBackfillStatus.SUCCEEDED
    assert [entry.canonical_sequence for entry in resumed.entries] == [1, 2]
    page = store.read_stream(_stream_request("run:run-1", through_sequence=2))
    assert [event.event_id for event in page.events] == ["evt-1", "evt-2"]


def test_backfill_resume_rejects_missing_staging_progress(tmp_path) -> None:
    records = (_event_record(),)
    _, backfill, report_store = _backfill(tmp_path)
    report = backfill.run(
        records,
        report_id="missing-progress",
        source_fingerprint=SOURCE_FINGERPRINT,
        records_fingerprint=migration_records_fingerprint(records),
        verify_source_fingerprint=lambda: SOURCE_FINGERPRINT,
    )
    assert report.status is MigrationBackfillStatus.SUCCEEDED

    empty_store = SQLiteEventStore(tmp_path / "empty.sqlite3", clock=lambda: NOW)
    with pytest.raises(MigrationResumeError, match="staging event"):
        EventMigrationBackfill(
            store=empty_store,
            report_store=report_store,
            project_event=_project_event,
            clock=lambda: NOW,
        ).run(
            records,
            report_id="missing-progress",
            source_fingerprint=SOURCE_FINGERPRINT,
            records_fingerprint=migration_records_fingerprint(records),
            verify_source_fingerprint=lambda: SOURCE_FINGERPRINT,
        )


def test_backfill_marks_changed_source_and_empty_source_deterministically(
    tmp_path,
) -> None:
    records = (_event_record(),)
    _, backfill, report_store = _backfill(tmp_path)
    changed = checksum_for({"source": "changed"})

    with pytest.raises(MigrationSourceChangedError, match="source changed"):
        backfill.run(
            records,
            report_id="changed-source",
            source_fingerprint=SOURCE_FINGERPRINT,
            records_fingerprint=migration_records_fingerprint(records),
            verify_source_fingerprint=lambda: changed,
        )
    failed = report_store.load("changed-source")
    assert failed is not None
    assert failed.status is MigrationBackfillStatus.FAILED
    assert failed.error_reason_class == "source_fingerprint_changed"

    _, empty_backfill, empty_report_store = _backfill(
        tmp_path,
        database_name="empty-events.sqlite3",
        report_name="empty-backfill.json",
    )
    empty_records: tuple[MigrationSourceRecord, ...] = ()
    empty = empty_backfill.run(
        empty_records,
        report_id="empty-source",
        source_fingerprint=SOURCE_FINGERPRINT,
        records_fingerprint=migration_records_fingerprint(empty_records),
        verify_source_fingerprint=lambda: SOURCE_FINGERPRINT,
    )
    assert empty.status is MigrationBackfillStatus.SUCCEEDED
    assert empty.counts["total"] == 0
    assert empty_report_store.load("empty-source") == empty


def test_shadow_compare_is_read_only_and_blocks_unexplained_history(tmp_path) -> None:
    first = (_event_record(event_id="evt-1"),)
    store, backfill, _ = _backfill(tmp_path)
    report = backfill.run(
        first,
        report_id="shadow-source",
        source_fingerprint=SOURCE_FINGERPRINT,
        records_fingerprint=migration_records_fingerprint(first),
        verify_source_fingerprint=lambda: SOURCE_FINGERPRINT,
    )
    comparator = MigrationShadowComparator(
        store,
        project_event=_project_event,
        clock=lambda: NOW,
    )

    matched = comparator.compare(report)

    assert matched.cutover_ready is True
    assert matched.expected_event_count == matched.actual_event_count == 1
    shadow_path = write_migration_shadow_report(
        tmp_path / "shadow.json",
        matched,
    )
    assert read_migration_shadow_report(shadow_path) == matched
    assert store.get_stream_high_watermark("run:run-1") == 1

    second = (_event_record(location="other.jsonl:1", event_id="evt-2"),)
    EventMigrationBackfill(
        store=store,
        report_store=JsonMigrationBackfillReportStore(tmp_path / "other.json"),
        project_event=_project_event,
        clock=lambda: NOW,
    ).run(
        second,
        report_id="unexplained-event",
        source_fingerprint=SOURCE_FINGERPRINT,
        records_fingerprint=migration_records_fingerprint(second),
        verify_source_fingerprint=lambda: SOURCE_FINGERPRINT,
    )

    mismatched = comparator.compare(report)

    assert mismatched.cutover_ready is False
    assert {item.reason_class for item in mismatched.mismatches} >= {
        "high_watermark_mismatch",
        "event_count_mismatch",
    }
    assert store.get_stream_high_watermark("run:run-1") == 2


def test_shadow_compare_detects_projection_contract_drift(tmp_path) -> None:
    records = (_event_record(),)
    store, backfill, _ = _backfill(tmp_path)
    report = backfill.run(
        records,
        report_id="projection-drift",
        source_fingerprint=SOURCE_FINGERPRINT,
        records_fingerprint=migration_records_fingerprint(records),
        verify_source_fingerprint=lambda: SOURCE_FINGERPRINT,
    )

    def drifted_projection(event):
        return {**_project_event(event), "projection_contract": "changed"}

    shadow = MigrationShadowComparator(
        store,
        project_event=drifted_projection,
        clock=lambda: NOW,
    ).compare(report)

    assert shadow.cutover_ready is False
    assert [item.reason_class for item in shadow.mismatches] == [
        "projection_checksum_mismatch"
    ]


def test_atomic_report_replace_failure_preserves_previous_progress(
    tmp_path,
    monkeypatch,
) -> None:
    from infrastructure.storage.events import migration_reports

    report_store = JsonMigrationBackfillReportStore(tmp_path / "atomic.json")
    initial = MigrationBackfillReport(
        report_id="atomic-report",
        source_fingerprint=SOURCE_FINGERPRINT,
        records_fingerprint=checksum_for([]),
        status=MigrationBackfillStatus.RUNNING,
        started_at=NOW,
        updated_at=NOW,
    )
    report_store.save(initial)
    advanced = replace(initial, updated_at=NOW + timedelta(seconds=1))

    def fail_replace(source, destination):
        raise OSError("injected replace failure")

    monkeypatch.setattr(migration_reports.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        report_store.save(advanced)

    assert report_store.load("atomic-report") == initial
    assert list(tmp_path.glob(".atomic.json.*.tmp")) == []


def test_shadow_report_rejects_checksum_tampering() -> None:
    report = MigrationShadowReport(
        backfill_report_id="report-1",
        compared_at=NOW,
        expected_event_count=0,
        actual_event_count=0,
        mismatches=(),
    )
    payload = report.to_dict()
    payload["actual_event_count"] = 1

    with pytest.raises(ValueError, match="checksum"):
        MigrationShadowReport.from_dict(payload)


def _backfill(
    tmp_path,
    *,
    database_name: str = "events.sqlite3",
    report_name: str = "backfill.json",
):
    store = SQLiteEventStore(tmp_path / database_name, clock=lambda: NOW)
    report_store = JsonMigrationBackfillReportStore(tmp_path / report_name)
    return (
        store,
        EventMigrationBackfill(
            store=store,
            report_store=report_store,
            project_event=_project_event,
            clock=lambda: NOW,
        ),
        report_store,
    )


def _event_record(
    *,
    location: str = "events.jsonl:1",
    event_id: str = "evt-1",
) -> MigrationSourceRecord:
    return MigrationSourceRecord(
        source_kind=MigrationSourceKind.LEGACY_RUN_JSONL,
        location=location,
        value={
            "schema_version": "newsroom.event_record.v1",
            "event_id": event_id,
            "event_type": "workflow_started",
            "occurred_at": "2026-07-16T00:00:00Z",
            "run_id": "run-1",
            "payload": {"run_id": "run-1"},
        },
    )


def _checkpoint_record() -> MigrationSourceRecord:
    return MigrationSourceRecord(
        source_kind=MigrationSourceKind.CHECKPOINT,
        location="checkpoint.json",
        value={
            "checkpoint_id": "checkpoint-1",
            "run_id": "run-1",
            "event_offset": 0,
        },
    )


def _stream_request(stream_id: str, *, through_sequence: int):
    from framework.events.runtime.models import StreamReadRequest

    return StreamReadRequest(
        stream_id=stream_id,
        through_sequence=through_sequence,
        limit=100,
    )


def _project_event(event):
    return project_workflow_event(
        event,
        schema_catalog=default_event_schema_catalog(),
    )


class _FailOnAppendFactory:
    def __init__(self, unit_of_work_factory, *, call_number: int) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._call_number = call_number
        self._calls = 0

    def __call__(self):
        return _FailOnAppendUnitOfWork(self, self._unit_of_work_factory())


class _FailOnAppendUnitOfWork:
    def __init__(self, owner, unit_of_work) -> None:
        self._owner = owner
        self._unit_of_work = unit_of_work

    def __enter__(self):
        self._unit_of_work.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        return self._unit_of_work.__exit__(exc_type, exc, traceback)

    def append_event(self, event, **kwargs):
        self._owner._calls += 1
        if self._owner._calls == self._owner._call_number:
            raise RuntimeError("injected migration interruption")
        return self._unit_of_work.append_event(event, **kwargs)

    def settle_delivery(self, settlement):
        return self._unit_of_work.settle_delivery(settlement)

    def commit(self):
        return self._unit_of_work.commit()

    def rollback(self):
        return self._unit_of_work.rollback()
