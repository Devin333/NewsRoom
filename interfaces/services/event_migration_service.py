from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

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


PostgresReaderFactory = Callable[[str], Any]


class EventMigrationApplicationError(RuntimeError):
    """Bounded application error that is safe to expose at CLI boundaries."""


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
        legacy_paths = tuple(legacy_run_jsonl)
        local_paths = tuple(local_event_records)
        checkpoint_paths = tuple(checkpoints)
        harness_paths = tuple(harness_histories)
        try:
            before_by_source = _fingerprint_file_sources(
                legacy_run_jsonl=legacy_paths,
                local_event_records=local_paths,
                checkpoints=checkpoint_paths,
                harness_histories=harness_paths,
            )
            before = _flatten_source_fingerprints(before_by_source)
            records = self._source_records(
                source_fingerprints=before_by_source,
                include_postgres=include_postgres,
            )
            report = self._scanner.scan(records, fail_fast=fail_fast)
            after_by_source = _fingerprint_file_sources(
                legacy_run_jsonl=legacy_paths,
                local_event_records=local_paths,
                checkpoints=checkpoint_paths,
                harness_histories=harness_paths,
            )
        except MigrationSourceReadError as exc:
            raise EventMigrationApplicationError(str(exc)) from exc
        after = _flatten_source_fingerprints(after_by_source)
        if before != after:
            raise EventMigrationApplicationError(
                "migration source changed while the dry-run was scanning"
            )
        before_fingerprint = _aggregate_fingerprint(before)
        after_fingerprint = _aggregate_fingerprint(after)
        return replace(
            report,
            source_integrity=MigrationSourceIntegrityEvidence(
                file_count=len(before),
                before_fingerprint=before_fingerprint,
                after_fingerprint=after_fingerprint,
            ),
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
]
