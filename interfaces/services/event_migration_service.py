from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from framework.events.migration_backfill import (
    EventMigrationBackfill,
    MigrationBackfillReport,
    MigrationBackfillReportStorePort,
    MigrationShadowComparator,
    MigrationShadowReport,
    migration_records_fingerprint,
)
from framework.events.ports import EventStorePort
from framework.events.schema import EventSchemaCatalog
from framework.events.migration import (
    EventMigrationDryRun,
    MigrationDryRunReport,
    MigrationSourceKind,
    MigrationSourceIntegrityEvidence,
    MigrationSourceRecord,
)
from framework.events.canonical import checksum_for
from infrastructure.storage.events.migration_readers import (
    MigrationSourceReadError,
    PostgresEventMigrationReader,
    fingerprint_source_paths,
    iter_checkpoint_records,
    iter_jsonl_records,
)
from framework.workflow.runtime.event_projection import project_workflow_event


PostgresReaderFactory = Callable[[str], Any]


class EventMigrationApplicationError(RuntimeError):
    """Bounded application error that is safe to expose at CLI boundaries."""


@dataclass(frozen=True, slots=True)
class MigrationSourceSelection:
    legacy_run_jsonl: tuple[str | Path, ...] = ()
    local_event_records: tuple[str | Path, ...] = ()
    checkpoints: tuple[str | Path, ...] = ()
    harness_histories: tuple[str | Path, ...] = ()
    include_postgres: bool = False

    @classmethod
    def from_inputs(
        cls,
        *,
        legacy_run_jsonl: Iterable[str | Path] = (),
        local_event_records: Iterable[str | Path] = (),
        checkpoints: Iterable[str | Path] = (),
        harness_histories: Iterable[str | Path] = (),
        include_postgres: bool = False,
    ) -> MigrationSourceSelection:
        return cls(
            legacy_run_jsonl=tuple(legacy_run_jsonl),
            local_event_records=tuple(local_event_records),
            checkpoints=tuple(checkpoints),
            harness_histories=tuple(harness_histories),
            include_postgres=bool(include_postgres),
        )

    @property
    def has_source(self) -> bool:
        return bool(
            self.legacy_run_jsonl
            or self.local_event_records
            or self.checkpoints
            or self.harness_histories
            or self.include_postgres
        )


@dataclass(frozen=True, slots=True)
class MigrationSourceSnapshot:
    source_fingerprint: str
    records_fingerprint: str
    source_integrity: MigrationSourceIntegrityEvidence
    _records_factory: Callable[[], Iterator[MigrationSourceRecord]]

    def iter_records(self) -> Iterator[MigrationSourceRecord]:
        return self._records_factory()


class EventMigrationApplicationService:
    """Application boundary for the read-only event migration assessment."""

    def __init__(
        self,
        *,
        scanner: EventMigrationDryRun | None = None,
        postgres_reader_factory: PostgresReaderFactory | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._scanner = scanner or EventMigrationDryRun()
        self._postgres_reader_factory = postgres_reader_factory or PostgresEventMigrationReader
        self._env = dict(env) if env is not None else None

    def dry_run(
        self,
        *,
        legacy_run_jsonl: Iterable[str | Path] = (),
        local_event_records: Iterable[str | Path] = (),
        checkpoints: Iterable[str | Path] = (),
        harness_histories: Iterable[str | Path] = (),
        include_postgres: bool = False,
        fail_fast: bool = False,
    ) -> MigrationDryRunReport:
        selection = MigrationSourceSelection.from_inputs(
            legacy_run_jsonl=legacy_run_jsonl,
            local_event_records=local_event_records,
            checkpoints=checkpoints,
            harness_histories=harness_histories,
            include_postgres=include_postgres,
        )
        try:
            snapshot = self.capture_sources(selection)
            report = self._scanner.scan(
                snapshot.iter_records(),
                fail_fast=fail_fast,
            )
        except MigrationSourceReadError as exc:
            raise EventMigrationApplicationError(str(exc)) from exc
        return replace(
            report,
            source_integrity=snapshot.source_integrity,
        )

    def capture_sources(
        self,
        selection: MigrationSourceSelection,
    ) -> MigrationSourceSnapshot:
        if not isinstance(selection, MigrationSourceSelection):
            raise TypeError("selection must be a MigrationSourceSelection")
        before_by_source = _fingerprint_file_sources(
            legacy_run_jsonl=selection.legacy_run_jsonl,
            local_event_records=selection.local_event_records,
            checkpoints=selection.checkpoints,
            harness_histories=selection.harness_histories,
        )
        before = _flatten_source_fingerprints(before_by_source)

        def records_factory() -> Iterator[MigrationSourceRecord]:
            return self._source_records(
                source_fingerprints=before_by_source,
                include_postgres=selection.include_postgres,
            )

        records_fingerprint = migration_records_fingerprint(records_factory())
        after_by_source = _fingerprint_file_sources(
            legacy_run_jsonl=selection.legacy_run_jsonl,
            local_event_records=selection.local_event_records,
            checkpoints=selection.checkpoints,
            harness_histories=selection.harness_histories,
        )
        after = _flatten_source_fingerprints(after_by_source)
        if before != after:
            raise EventMigrationApplicationError(
                "migration source changed while the snapshot was captured"
            )
        before_fingerprint = _aggregate_fingerprint(before)
        after_fingerprint = _aggregate_fingerprint(after)
        return MigrationSourceSnapshot(
            source_fingerprint=checksum_for(
                {
                    "files": before,
                    "records_fingerprint": records_fingerprint,
                }
            ),
            records_fingerprint=records_fingerprint,
            source_integrity=MigrationSourceIntegrityEvidence(
                file_count=len(before),
                before_fingerprint=before_fingerprint,
                after_fingerprint=after_fingerprint,
            ),
            _records_factory=records_factory,
        )

    def _source_records(
        self,
        *,
        source_fingerprints: dict[MigrationSourceKind, dict[str, str]],
        include_postgres: bool,
    ) -> Iterator[MigrationSourceRecord]:
        legacy = source_fingerprints[MigrationSourceKind.LEGACY_RUN_JSONL]
        yield from iter_jsonl_records(
            legacy,
            source_kind=MigrationSourceKind.LEGACY_RUN_JSONL,
            expected_fingerprints=legacy,
        )
        local = source_fingerprints[MigrationSourceKind.LOCAL_EVENT_RECORD]
        yield from iter_jsonl_records(
            local,
            source_kind=MigrationSourceKind.LOCAL_EVENT_RECORD,
            expected_fingerprints=local,
        )
        if include_postgres:
            dsn = (self._env if self._env is not None else os.environ).get(
                "NEWS_DATABASE_DSN"
            )
            if not dsn:
                raise ValueError(
                    "PostgreSQL migration scan requires NEWS_DATABASE_DSN"
                )
            try:
                yield from self._postgres_reader_factory(dsn).iter_records()
            except MigrationSourceReadError:
                raise
            except Exception as exc:
                raise MigrationSourceReadError(
                    MigrationSourceKind.POSTGRESQL_ROW
                ) from exc
        checkpoint = source_fingerprints[MigrationSourceKind.CHECKPOINT]
        yield from iter_checkpoint_records(
            checkpoint,
            expected_fingerprints=checkpoint,
        )
        harness = source_fingerprints[MigrationSourceKind.HARNESS_HISTORY]
        yield from iter_jsonl_records(
            harness,
            source_kind=MigrationSourceKind.HARNESS_HISTORY,
            expected_fingerprints=harness,
        )


class EventMigrationBackfillApplicationService:
    """Application composition for staging import and read-only shadow compare."""

    def __init__(
        self,
        *,
        source_service: EventMigrationApplicationService,
        staging_store: EventStorePort,
        schema_catalog: EventSchemaCatalog,
        report_store: MigrationBackfillReportStorePort,
        clock: Callable[[], Any] | None = None,
    ) -> None:
        self._source_service = source_service
        self._report_store = report_store
        if not isinstance(schema_catalog, EventSchemaCatalog):
            raise TypeError("schema_catalog must be an EventSchemaCatalog")

        def project_event(event):
            return project_workflow_event(event, schema_catalog=schema_catalog)

        self._backfill = EventMigrationBackfill(
            store=staging_store,
            report_store=report_store,
            project_event=project_event,
            clock=clock,
        )
        self._shadow = MigrationShadowComparator(
            staging_store,
            project_event=project_event,
            clock=clock,
        )

    def backfill(
        self,
        selection: MigrationSourceSelection,
        *,
        report_id: str,
        resume: bool = True,
    ) -> MigrationBackfillReport:
        if not selection.has_source:
            raise EventMigrationApplicationError(
                "migration backfill requires at least one source"
            )
        snapshot = self._source_service.capture_sources(selection)

        def verify_source() -> str:
            return self._source_service.capture_sources(selection).source_fingerprint

        return self._backfill.run(
            snapshot.iter_records(),
            report_id=report_id,
            source_fingerprint=snapshot.source_fingerprint,
            records_fingerprint=snapshot.records_fingerprint,
            verify_source_fingerprint=verify_source,
            resume=resume,
        )

    def shadow_compare(self, *, report_id: str) -> MigrationShadowReport:
        report = self._report_store.load(report_id)
        if report is None:
            raise EventMigrationApplicationError("migration backfill report was not found")
        return self._shadow.compare(report)


def _fingerprint_file_sources(
    *,
    legacy_run_jsonl: Iterable[str | Path],
    local_event_records: Iterable[str | Path],
    checkpoints: Iterable[str | Path],
    harness_histories: Iterable[str | Path],
) -> dict[MigrationSourceKind, dict[str, str]]:
    fingerprints: dict[MigrationSourceKind, dict[str, str]] = {}
    for source_kind, paths, suffix in (
        (MigrationSourceKind.LEGACY_RUN_JSONL, legacy_run_jsonl, ".jsonl"),
        (MigrationSourceKind.LOCAL_EVENT_RECORD, local_event_records, ".jsonl"),
        (MigrationSourceKind.CHECKPOINT, checkpoints, ".json"),
        (MigrationSourceKind.HARNESS_HISTORY, harness_histories, ".jsonl"),
    ):
        fingerprints[source_kind] = fingerprint_source_paths(
            paths,
            suffix=suffix,
            source_kind=source_kind,
        )
    return fingerprints


def _flatten_source_fingerprints(
    fingerprints: dict[MigrationSourceKind, dict[str, str]],
) -> dict[str, str]:
    return {
        f"{source_kind.value}:{path}": digest
        for source_kind in MigrationSourceKind
        if source_kind is not MigrationSourceKind.POSTGRESQL_ROW
        for path, digest in sorted(fingerprints[source_kind].items())
    }


def _aggregate_fingerprint(fingerprints: dict[str, str]) -> str:
    return checksum_for(fingerprints)


__all__ = [
    "EventMigrationApplicationError",
    "EventMigrationApplicationService",
    "EventMigrationBackfillApplicationService",
    "MigrationSourceSelection",
    "MigrationSourceSnapshot",
]
