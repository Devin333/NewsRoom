from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any, Protocol

from framework.events.canonical import (
    EventCandidate,
    StoredEvent,
    checksum_for,
    thaw_canonical_json,
)
from framework.events.errors import (
    EventContextConflictError,
    EventQuarantineError,
    EventSecurityError,
    EventUnknownSchemaError,
)
from framework.events.migration import (
    EventMigrationDryRun,
    MigrationMappedRecord,
    MigrationSourceKind,
    MigrationSourceRecord,
)
from framework.events.ports import EventReaderPort, EventStorePort
from framework.events.runtime.models import MAX_PAGE_LIMIT, StreamReadRequest
from framework.shared.json import stable_json_dumps


BACKFILL_REPORT_SCHEMA = "newsroom.event-migration-backfill/v1"
SHADOW_REPORT_SCHEMA = "newsroom.event-migration-shadow/v1"


class MigrationBackfillStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MigrationImportDisposition(StrEnum):
    IMPORTED = "imported"
    DUPLICATE = "duplicate"
    CHECKPOINT_MAPPED = "checkpoint_mapped"
    QUARANTINED = "quarantined"


class MigrationBackfillError(RuntimeError):
    """Base error for a bounded staging import operation."""


class MigrationResumeError(MigrationBackfillError):
    """Persisted progress cannot safely resume against the staging store."""


class MigrationSourceChangedError(MigrationBackfillError):
    """The source snapshot changed before or while the import ran."""


class MigrationShadowMismatchError(MigrationBackfillError):
    """A shadow comparison was requested for an incomplete import."""


@dataclass(frozen=True, slots=True)
class MigrationImportEntry:
    source_identity: str
    source_kind: MigrationSourceKind | str
    source_location: str
    disposition: MigrationImportDisposition | str
    reason: str
    identity_namespace: str | None = None
    event_id: str | None = None
    content_checksum: str | None = None
    stream_id: str | None = None
    tenant_id: str | None = None
    legacy_offset: int | None = None
    source_sequence: int | None = None
    canonical_sequence: int | None = None
    canonical_record_checksum: str | None = None
    canonical_projection_checksum: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_identity",
            _checksum(self.source_identity, "source_identity"),
        )
        object.__setattr__(self, "source_kind", MigrationSourceKind(self.source_kind))
        location = _required_text(self.source_location, "source_location")
        if len(location) > 2_048:
            raise ValueError("source_location exceeds 2048 characters")
        object.__setattr__(self, "source_location", location)
        disposition = MigrationImportDisposition(self.disposition)
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "reason", _reason_class(self.reason))
        for field_name in (
            "identity_namespace",
            "event_id",
            "stream_id",
            "tenant_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name), field_name),
            )
        if self.content_checksum is not None:
            object.__setattr__(
                self,
                "content_checksum",
                _checksum(self.content_checksum, "content_checksum"),
            )
        if self.canonical_record_checksum is not None:
            object.__setattr__(
                self,
                "canonical_record_checksum",
                _checksum(
                    self.canonical_record_checksum,
                    "canonical_record_checksum",
                ),
            )
        if self.canonical_projection_checksum is not None:
            object.__setattr__(
                self,
                "canonical_projection_checksum",
                _checksum(
                    self.canonical_projection_checksum,
                    "canonical_projection_checksum",
                ),
            )
        _optional_integer(self.legacy_offset, "legacy_offset", minimum=0)
        _optional_integer(self.source_sequence, "source_sequence", minimum=1)
        _optional_integer(self.canonical_sequence, "canonical_sequence", minimum=1)
        if disposition in {
            MigrationImportDisposition.IMPORTED,
            MigrationImportDisposition.DUPLICATE,
        }:
            required = (
                self.identity_namespace,
                self.event_id,
                self.content_checksum,
                self.stream_id,
                self.canonical_sequence,
                self.canonical_record_checksum,
                self.canonical_projection_checksum,
            )
            if any(value is None for value in required):
                raise ValueError("imported event mapping is incomplete")
        if (
            disposition is MigrationImportDisposition.CHECKPOINT_MAPPED
            and (self.identity_namespace != "checkpoint" or self.event_id is None)
        ):
            raise ValueError("checkpoint mapping is incomplete")

    @property
    def dedupe_key(self) -> str | None:
        if self.identity_namespace is None or self.event_id is None:
            return None
        return f"{self.identity_namespace}:{self.event_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_identity": self.source_identity,
            "source_kind": self.source_kind.value,
            "source_location": self.source_location,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "identity_namespace": self.identity_namespace,
            "event_id": self.event_id,
            "content_checksum": self.content_checksum,
            "stream_id": self.stream_id,
            "tenant_id": self.tenant_id,
            "legacy_offset": self.legacy_offset,
            "source_sequence": self.source_sequence,
            "canonical_sequence": self.canonical_sequence,
            "canonical_record_checksum": self.canonical_record_checksum,
            "canonical_projection_checksum": self.canonical_projection_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> MigrationImportEntry:
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class MigrationBackfillReport:
    report_id: str
    source_fingerprint: str
    records_fingerprint: str
    status: MigrationBackfillStatus | str
    entries: tuple[MigrationImportEntry, ...] = ()
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error_reason_class: str | None = None
    schema_version: str = BACKFILL_REPORT_SCHEMA
    report_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "report_id", _required_text(self.report_id, "report_id"))
        object.__setattr__(
            self,
            "source_fingerprint",
            _checksum(self.source_fingerprint, "source_fingerprint"),
        )
        object.__setattr__(
            self,
            "records_fingerprint",
            _checksum(self.records_fingerprint, "records_fingerprint"),
        )
        status = MigrationBackfillStatus(self.status)
        object.__setattr__(self, "status", status)
        entries = tuple(self.entries)
        if any(not isinstance(entry, MigrationImportEntry) for entry in entries):
            raise TypeError("entries must contain MigrationImportEntry values")
        identities = [entry.source_identity for entry in entries]
        if len(identities) != len(set(identities)):
            raise ValueError("migration report contains duplicate source identities")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "started_at", _utc(self.started_at, "started_at"))
        object.__setattr__(self, "updated_at", _utc(self.updated_at, "updated_at"))
        if self.updated_at < self.started_at:
            raise ValueError("updated_at cannot precede started_at")
        reason = (
            None
            if self.error_reason_class is None
            else _reason_class(self.error_reason_class)
        )
        if status is MigrationBackfillStatus.FAILED and reason is None:
            raise ValueError("failed migration report requires a reason class")
        if status is not MigrationBackfillStatus.FAILED and reason is not None:
            raise ValueError("non-failed migration report cannot contain an error reason")
        object.__setattr__(self, "error_reason_class", reason)
        if self.schema_version != BACKFILL_REPORT_SCHEMA:
            raise ValueError("unsupported migration backfill report schema")
        object.__setattr__(self, "report_checksum", checksum_for(self.checksum_projection()))

    @property
    def counts(self) -> dict[str, int]:
        counts = {disposition.value: 0 for disposition in MigrationImportDisposition}
        for entry in self.entries:
            counts[entry.disposition.value] += 1
        counts["total"] = len(self.entries)
        return counts

    @property
    def completed_source_identities(self) -> frozenset[str]:
        return frozenset(entry.source_identity for entry in self.entries)

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "source_fingerprint": self.source_fingerprint,
            "records_fingerprint": self.records_fingerprint,
            "status": self.status.value,
            "entries": [entry.to_dict() for entry in self.entries],
            "started_at": _format_time(self.started_at),
            "updated_at": _format_time(self.updated_at),
            "error_reason_class": self.error_reason_class,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "counts": self.counts,
            "report_checksum": self.report_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> MigrationBackfillReport:
        entries = tuple(
            MigrationImportEntry.from_dict(item)
            for item in _mapping_list(value.get("entries"), "entries")
        )
        report = cls(
            schema_version=str(value.get("schema_version") or ""),
            report_id=str(value.get("report_id") or ""),
            source_fingerprint=str(value.get("source_fingerprint") or ""),
            records_fingerprint=str(value.get("records_fingerprint") or ""),
            status=str(value.get("status") or ""),
            entries=entries,
            started_at=_parse_time(value.get("started_at"), "started_at"),
            updated_at=_parse_time(value.get("updated_at"), "updated_at"),
            error_reason_class=value.get("error_reason_class"),
        )
        supplied = _checksum(value.get("report_checksum"), "report_checksum")
        if supplied != report.report_checksum:
            raise ValueError("migration backfill report checksum does not match")
        supplied_counts = value.get("counts")
        if supplied_counts is not None and dict(supplied_counts) != report.counts:
            raise ValueError("migration backfill report counts do not match")
        return report


class MigrationBackfillReportStorePort(Protocol):
    def load(self, report_id: str) -> MigrationBackfillReport | None: ...

    def save(self, report: MigrationBackfillReport) -> None: ...


class EventMigrationBackfill:
    """Resume-safe import into a staging canonical runtime."""

    def __init__(
        self,
        *,
        store: EventStorePort,
        report_store: MigrationBackfillReportStorePort,
        project_event: Callable[[StoredEvent], Mapping[str, Any]],
        mapper: EventMigrationDryRun | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(store, EventStorePort):
            raise TypeError("store must implement EventStorePort")
        self._store = store
        self._reader = store
        self._report_store = report_store
        if not callable(project_event):
            raise TypeError("project_event must be callable")
        self._project_event = project_event
        self._mapper = mapper or EventMigrationDryRun()
        self._clock = clock or (lambda: datetime.now(UTC))

    def run(
        self,
        records: Iterable[MigrationSourceRecord],
        *,
        report_id: str,
        source_fingerprint: str,
        records_fingerprint: str,
        verify_source_fingerprint: Callable[[], str],
        resume: bool = True,
    ) -> MigrationBackfillReport:
        normalized_source = _checksum(source_fingerprint, "source_fingerprint")
        normalized_records = _checksum(records_fingerprint, "records_fingerprint")
        now = _utc(self._clock(), "clock")
        report = self._report_store.load(report_id)
        if report is None:
            report = MigrationBackfillReport(
                report_id=report_id,
                source_fingerprint=normalized_source,
                records_fingerprint=normalized_records,
                status=MigrationBackfillStatus.RUNNING,
                started_at=now,
                updated_at=now,
            )
            self._report_store.save(report)
        else:
            if not resume:
                raise MigrationResumeError("migration report already exists")
            self._validate_resume_report(
                report,
                source_fingerprint=normalized_source,
                records_fingerprint=normalized_records,
            )
            self._verify_staging_entries(report.entries)
            if report.status is MigrationBackfillStatus.SUCCEEDED:
                return report

        entries = list(report.entries)
        completed = {entry.source_identity: entry for entry in entries}
        seen = {
            entry.dedupe_key: entry
            for entry in entries
            if entry.dedupe_key is not None
            and entry.disposition
            in {
                MigrationImportDisposition.IMPORTED,
                MigrationImportDisposition.DUPLICATE,
                MigrationImportDisposition.CHECKPOINT_MAPPED,
            }
        }
        digest = sha256()
        for record in records:
            _update_records_digest(digest, record)
            source_identity = migration_source_identity(record)
            existing = completed.get(source_identity)
            if existing is not None:
                self._verify_source_mapping(record, existing)
                continue
            entry = self._apply_record(record, source_identity=source_identity, seen=seen)
            entries.append(entry)
            completed[source_identity] = entry
            if entry.dedupe_key is not None and entry.disposition is not MigrationImportDisposition.QUARANTINED:
                seen.setdefault(entry.dedupe_key, entry)
            report = replace(
                report,
                entries=tuple(entries),
                updated_at=_utc(self._clock(), "clock"),
            )
            self._report_store.save(report)

        actual_records = f"sha256:{digest.hexdigest()}"
        if actual_records != normalized_records:
            self._fail_report(report, "source_records_changed")
            raise MigrationSourceChangedError("migration source records changed")
        try:
            observed_source = _checksum(
                verify_source_fingerprint(),
                "observed_source_fingerprint",
            )
        except Exception:
            self._fail_report(report, "source_fingerprint_unavailable")
            raise MigrationSourceChangedError(
                "migration source fingerprint could not be verified"
            ) from None
        if observed_source != normalized_source:
            self._fail_report(report, "source_fingerprint_changed")
            raise MigrationSourceChangedError("migration source changed")
        self._verify_staging_entries(tuple(entries))
        report = replace(
            report,
            status=MigrationBackfillStatus.SUCCEEDED,
            updated_at=_utc(self._clock(), "clock"),
        )
        self._report_store.save(report)
        return report

    def _apply_record(
        self,
        record: MigrationSourceRecord,
        *,
        source_identity: str,
        seen: dict[str | None, MigrationImportEntry],
    ) -> MigrationImportEntry:
        try:
            mapped = self._mapper.map_record(record)
        except Exception as error:
            return _quarantine_entry(
                record,
                source_identity=source_identity,
                reason=_mapping_failure_reason(error),
            )
        if mapped.identity_namespace != "event":
            return _entry_from_mapping(
                record,
                mapped,
                source_identity=source_identity,
                disposition=MigrationImportDisposition.CHECKPOINT_MAPPED,
                reason="checkpoint_mapping_recorded",
            )
        candidate = mapped.candidate
        assert candidate is not None
        previous = seen.get(mapped.dedupe_key)
        if previous is not None and previous.content_checksum != mapped.content_checksum:
            return _quarantine_entry(
                record,
                source_identity=source_identity,
                reason="same_event_id_different_content",
                mapped=mapped,
            )
        existing_stored = self._reader.get_event(
            mapped.event_id,
            tenant_id=candidate.tenant_id,
        )
        if (
            existing_stored is not None
            and existing_stored.content_checksum != mapped.content_checksum
        ):
            return _quarantine_entry(
                record,
                source_identity=source_identity,
                reason="staging_identity_collision",
                mapped=mapped,
            )
        expected_last_sequence = (
            None
            if mapped.source_sequence is None
            else mapped.source_sequence - 1
        )
        with self._store.unit_of_work() as unit_of_work:
            append_result = unit_of_work.append_event(
                candidate,
                expected_last_sequence=expected_last_sequence,
            )
            if append_result.pending_delivery_count:
                raise MigrationBackfillError(
                    "staging import cannot materialize delivery work"
                )
            unit_of_work.commit()
        stored = append_result.event
        _verify_stored_mapping(stored, mapped)
        duplicate = (
            previous is not None
            or existing_stored is not None
            or not append_result.created
        )
        return _entry_from_mapping(
            record,
            mapped,
            source_identity=source_identity,
            disposition=(
                MigrationImportDisposition.DUPLICATE
                if duplicate
                else MigrationImportDisposition.IMPORTED
            ),
            reason=(
                "same_event_id_same_content"
                if duplicate
                else "canonical_event_imported"
            ),
            stored=stored,
            canonical_projection_checksum=checksum_for(
                self._project_event(stored)
            ),
        )

    def _validate_resume_report(
        self,
        report: MigrationBackfillReport,
        *,
        source_fingerprint: str,
        records_fingerprint: str,
    ) -> None:
        if report.source_fingerprint != source_fingerprint:
            raise MigrationResumeError("migration source fingerprint changed")
        if report.records_fingerprint != records_fingerprint:
            raise MigrationResumeError("migration record fingerprint changed")
        if report.status is MigrationBackfillStatus.FAILED:
            raise MigrationResumeError("failed migration report cannot resume")

    def _verify_staging_entries(
        self,
        entries: tuple[MigrationImportEntry, ...],
    ) -> None:
        verified: set[tuple[str, str | None]] = set()
        for entry in entries:
            if entry.disposition not in {
                MigrationImportDisposition.IMPORTED,
                MigrationImportDisposition.DUPLICATE,
            }:
                continue
            assert entry.event_id is not None
            key = (entry.event_id, entry.tenant_id)
            if key in verified:
                continue
            verified.add(key)
            stored = self._reader.get_event(entry.event_id, tenant_id=entry.tenant_id)
            if stored is None or not _stored_matches_entry(
                stored,
                entry,
                project_event=self._project_event,
            ):
                raise MigrationResumeError(
                    "staging event does not match persisted migration progress"
                )

    def _verify_source_mapping(
        self,
        record: MigrationSourceRecord,
        entry: MigrationImportEntry,
    ) -> None:
        try:
            mapped = self._mapper.map_record(record)
        except Exception as error:
            if (
                entry.disposition is not MigrationImportDisposition.QUARANTINED
                or entry.reason != _mapping_failure_reason(error)
            ):
                raise MigrationResumeError(
                    "source mapping no longer matches persisted progress"
                ) from None
            return
        expected = (
            mapped.identity_namespace,
            mapped.event_id,
            mapped.content_checksum,
            mapped.legacy_offset,
            mapped.source_sequence,
        )
        actual = (
            entry.identity_namespace,
            entry.event_id,
            entry.content_checksum,
            entry.legacy_offset,
            entry.source_sequence,
        )
        if expected != actual:
            raise MigrationResumeError(
                "source mapping no longer matches persisted progress"
            )

    def _fail_report(
        self,
        report: MigrationBackfillReport,
        reason: str,
    ) -> None:
        self._report_store.save(
            replace(
                report,
                status=MigrationBackfillStatus.FAILED,
                error_reason_class=reason,
                updated_at=_utc(self._clock(), "clock"),
            )
        )


@dataclass(frozen=True, slots=True)
class MigrationShadowMismatch:
    reason_class: str
    stream_id: str | None = None
    event_id: str | None = None
    expected: str | int | None = None
    actual: str | int | None = None
    severity: str = "p1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_class", _reason_class(self.reason_class))
        for field_name in ("stream_id", "event_id"):
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name), field_name),
            )
        for field_name in ("expected", "actual"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (str, int))
            ):
                raise TypeError(f"{field_name} must be a string or integer")
        if self.severity != "p1":
            raise ValueError("migration shadow mismatches must be P1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "reason_class": self.reason_class,
            "stream_id": self.stream_id,
            "event_id": self.event_id,
            "expected": self.expected,
            "actual": self.actual,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> MigrationShadowMismatch:
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class MigrationShadowReport:
    backfill_report_id: str
    compared_at: datetime
    expected_event_count: int
    actual_event_count: int
    mismatches: tuple[MigrationShadowMismatch, ...]
    schema_version: str = SHADOW_REPORT_SCHEMA
    report_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "backfill_report_id",
            _required_text(self.backfill_report_id, "backfill_report_id"),
        )
        object.__setattr__(self, "compared_at", _utc(self.compared_at, "compared_at"))
        _integer(self.expected_event_count, "expected_event_count", minimum=0)
        _integer(self.actual_event_count, "actual_event_count", minimum=0)
        mismatches = tuple(self.mismatches)
        if any(not isinstance(item, MigrationShadowMismatch) for item in mismatches):
            raise TypeError("mismatches must contain MigrationShadowMismatch values")
        object.__setattr__(self, "mismatches", mismatches)
        if self.schema_version != SHADOW_REPORT_SCHEMA:
            raise ValueError("unsupported migration shadow report schema")
        object.__setattr__(self, "report_checksum", checksum_for(self.checksum_projection()))

    @property
    def cutover_ready(self) -> bool:
        return not self.mismatches

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "backfill_report_id": self.backfill_report_id,
            "compared_at": _format_time(self.compared_at),
            "expected_event_count": self.expected_event_count,
            "actual_event_count": self.actual_event_count,
            "mismatches": [item.to_dict() for item in self.mismatches],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "cutover_ready": self.cutover_ready,
            "report_checksum": self.report_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> MigrationShadowReport:
        report = cls(
            schema_version=str(value.get("schema_version") or ""),
            backfill_report_id=str(value.get("backfill_report_id") or ""),
            compared_at=_parse_time(value.get("compared_at"), "compared_at"),
            expected_event_count=_integer_value(
                value.get("expected_event_count"),
                "expected_event_count",
                minimum=0,
            ),
            actual_event_count=_integer_value(
                value.get("actual_event_count"),
                "actual_event_count",
                minimum=0,
            ),
            mismatches=tuple(
                MigrationShadowMismatch.from_dict(item)
                for item in _mapping_list(value.get("mismatches"), "mismatches")
            ),
        )
        supplied = _checksum(value.get("report_checksum"), "report_checksum")
        if supplied != report.report_checksum:
            raise ValueError("migration shadow report checksum does not match")
        cutover_ready = value.get("cutover_ready")
        if cutover_ready is not None and cutover_ready is not report.cutover_ready:
            raise ValueError("migration shadow report cutover status does not match")
        return report


class MigrationShadowComparator:
    """Read-only comparison; it has no runtime, bus, or dispatcher dependency."""

    def __init__(
        self,
        reader: EventReaderPort,
        *,
        project_event: Callable[[StoredEvent], Mapping[str, Any]],
        clock: Callable[[], datetime] | None = None,
        page_size: int = 1_000,
    ) -> None:
        if not 1 <= page_size <= MAX_PAGE_LIMIT:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_LIMIT}")
        self._reader = reader
        if not callable(project_event):
            raise TypeError("project_event must be callable")
        self._project_event = project_event
        self._clock = clock or (lambda: datetime.now(UTC))
        self._page_size = page_size

    def compare(self, report: MigrationBackfillReport) -> MigrationShadowReport:
        if report.status is not MigrationBackfillStatus.SUCCEEDED:
            raise MigrationShadowMismatchError(
                "shadow comparison requires a successful backfill report"
            )
        mismatches: list[MigrationShadowMismatch] = []
        for entry in report.entries:
            if entry.disposition is MigrationImportDisposition.QUARANTINED:
                mismatches.append(
                    MigrationShadowMismatch(
                        reason_class="unresolved_quarantine",
                        event_id=entry.event_id,
                    )
                )
        expected_by_stream: dict[
            tuple[str | None, str], dict[str, MigrationImportEntry]
        ] = {}
        for entry in report.entries:
            if entry.disposition not in {
                MigrationImportDisposition.IMPORTED,
                MigrationImportDisposition.DUPLICATE,
            }:
                continue
            assert entry.stream_id is not None and entry.event_id is not None
            expected_by_stream.setdefault(
                (entry.tenant_id, entry.stream_id), {}
            ).setdefault(entry.event_id, entry)

        actual_total = 0
        for (tenant_id, stream_id), by_id in sorted(
            expected_by_stream.items(),
            key=lambda item: ((item[0][0] or ""), item[0][1]),
        ):
            expected = sorted(
                by_id.values(),
                key=lambda entry: int(entry.canonical_sequence or 0),
            )
            expected_high = max(int(entry.canonical_sequence or 0) for entry in expected)
            actual_high = self._reader.get_stream_high_watermark(
                stream_id,
                tenant_id=tenant_id,
            )
            if actual_high != expected_high:
                mismatches.append(
                    MigrationShadowMismatch(
                        reason_class="high_watermark_mismatch",
                        stream_id=stream_id,
                        expected=expected_high,
                        actual=actual_high,
                    )
                )
            actual = self._read_stream(
                stream_id,
                tenant_id=tenant_id,
                high_watermark=actual_high,
            )
            actual_total += len(actual)
            if len(actual) != len(expected):
                mismatches.append(
                    MigrationShadowMismatch(
                        reason_class="event_count_mismatch",
                        stream_id=stream_id,
                        expected=len(expected),
                        actual=len(actual),
                    )
                )
            for index, expected_entry in enumerate(expected):
                if (
                    expected_entry.source_sequence is not None
                    and expected_entry.source_sequence
                    != expected_entry.canonical_sequence
                ):
                    mismatches.append(
                        MigrationShadowMismatch(
                            reason_class="source_sequence_mismatch",
                            stream_id=stream_id,
                            event_id=expected_entry.event_id,
                            expected=expected_entry.source_sequence,
                            actual=expected_entry.canonical_sequence,
                        )
                    )
                if index >= len(actual):
                    continue
                stored = actual[index]
                comparisons = (
                    ("event_order_mismatch", expected_entry.event_id, stored.event_id),
                    (
                        "content_checksum_mismatch",
                        expected_entry.content_checksum,
                        stored.content_checksum,
                    ),
                    (
                        "canonical_sequence_mismatch",
                        expected_entry.canonical_sequence,
                        stored.stream_sequence,
                    ),
                    (
                        "record_checksum_mismatch",
                        expected_entry.canonical_record_checksum,
                        stored.record_checksum,
                    ),
                    (
                        "projection_checksum_mismatch",
                        expected_entry.canonical_projection_checksum,
                        checksum_for(self._project_event(stored)),
                    ),
                )
                for reason, expected_value, actual_value in comparisons:
                    if expected_value != actual_value:
                        mismatches.append(
                            MigrationShadowMismatch(
                                reason_class=reason,
                                stream_id=stream_id,
                                event_id=expected_entry.event_id,
                                expected=expected_value,
                                actual=actual_value,
                            )
                        )
        expected_total = sum(len(items) for items in expected_by_stream.values())
        return MigrationShadowReport(
            backfill_report_id=report.report_id,
            compared_at=_utc(self._clock(), "clock"),
            expected_event_count=expected_total,
            actual_event_count=actual_total,
            mismatches=tuple(mismatches),
        )

    def _read_stream(
        self,
        stream_id: str,
        *,
        tenant_id: str | None,
        high_watermark: int | None,
    ) -> tuple[StoredEvent, ...]:
        if high_watermark is None:
            return ()
        request = StreamReadRequest(
            stream_id=stream_id,
            tenant_id=tenant_id,
            limit=self._page_size,
            through_sequence=high_watermark,
        )
        events: list[StoredEvent] = []
        while True:
            page = self._reader.read_stream(request)
            if (
                page.stream_id != stream_id
                or page.tenant_id != tenant_id
                or page.high_watermark != high_watermark
            ):
                raise MigrationShadowMismatchError(
                    "event reader changed the shadow comparison scope"
                )
            events.extend(page.events)
            if page.next_cursor is None:
                return tuple(events)
            request = StreamReadRequest(
                stream_id=stream_id,
                tenant_id=tenant_id,
                cursor=page.next_cursor,
                limit=self._page_size,
                through_sequence=high_watermark,
            )


def migration_records_fingerprint(
    records: Iterable[MigrationSourceRecord],
) -> str:
    digest = sha256()
    for record in records:
        _update_records_digest(digest, record)
    return f"sha256:{digest.hexdigest()}"


def migration_source_identity(record: MigrationSourceRecord) -> str:
    if not isinstance(record, MigrationSourceRecord):
        raise TypeError("record must be a MigrationSourceRecord")
    return checksum_for(
        {
            "source_kind": record.source_kind.value,
            "source_location": record.location,
        }
    )


def _update_records_digest(digest: Any, record: MigrationSourceRecord) -> None:
    if not isinstance(record, MigrationSourceRecord):
        raise TypeError("records must contain MigrationSourceRecord values")
    projection = {
        "source_kind": record.source_kind.value,
        "source_location": record.location,
        "issue_reason": record.issue_reason,
        "value": (
            None
            if record.value is None
            else thaw_canonical_json(record.value)
        ),
    }
    digest.update(stable_json_dumps(projection).encode("utf-8"))
    digest.update(b"\n")


def _entry_from_mapping(
    record: MigrationSourceRecord,
    mapped: MigrationMappedRecord,
    *,
    source_identity: str,
    disposition: MigrationImportDisposition,
    reason: str,
    stored: StoredEvent | None = None,
    canonical_projection_checksum: str | None = None,
) -> MigrationImportEntry:
    candidate = mapped.candidate
    return MigrationImportEntry(
        source_identity=source_identity,
        source_kind=record.source_kind,
        source_location=record.location,
        disposition=disposition,
        reason=reason,
        identity_namespace=mapped.identity_namespace,
        event_id=mapped.event_id,
        content_checksum=mapped.content_checksum,
        stream_id=(candidate.stream_id if candidate is not None else None),
        tenant_id=(candidate.tenant_id if candidate is not None else None),
        legacy_offset=mapped.legacy_offset,
        source_sequence=mapped.source_sequence,
        canonical_sequence=(stored.stream_sequence if stored is not None else None),
        canonical_record_checksum=(stored.record_checksum if stored is not None else None),
        canonical_projection_checksum=canonical_projection_checksum,
    )


def _quarantine_entry(
    record: MigrationSourceRecord,
    *,
    source_identity: str,
    reason: str,
    mapped: MigrationMappedRecord | None = None,
) -> MigrationImportEntry:
    candidate = mapped.candidate if mapped is not None else None
    return MigrationImportEntry(
        source_identity=source_identity,
        source_kind=record.source_kind,
        source_location=record.location,
        disposition=MigrationImportDisposition.QUARANTINED,
        reason=reason,
        identity_namespace=(mapped.identity_namespace if mapped is not None else None),
        event_id=(mapped.event_id if mapped is not None else None),
        content_checksum=(mapped.content_checksum if mapped is not None else None),
        stream_id=(candidate.stream_id if candidate is not None else None),
        tenant_id=(candidate.tenant_id if candidate is not None else None),
        legacy_offset=(mapped.legacy_offset if mapped is not None else None),
        source_sequence=(mapped.source_sequence if mapped is not None else None),
    )


def _mapping_failure_reason(error: Exception) -> str:
    if isinstance(error, EventQuarantineError):
        return _reason_class(error.reason)
    if isinstance(error, EventContextConflictError):
        return "context_conflict"
    if isinstance(error, EventUnknownSchemaError):
        return "unknown_data_schema"
    if isinstance(error, EventSecurityError):
        return "security_policy_violation"
    if isinstance(error, (KeyError, TypeError, ValueError)):
        return "unsupported_legacy_mapping"
    raise error


def _verify_stored_mapping(stored: StoredEvent, mapped: MigrationMappedRecord) -> None:
    if (
        not isinstance(stored, StoredEvent)
        or stored.event_id != mapped.event_id
        or stored.content_checksum != mapped.content_checksum
    ):
        raise MigrationBackfillError(
            "staging runtime returned a different canonical event"
        )
    stored.verify_integrity()


def _stored_matches_entry(
    stored: StoredEvent,
    entry: MigrationImportEntry,
    *,
    project_event: Callable[[StoredEvent], Mapping[str, Any]],
) -> bool:
    try:
        stored.verify_integrity()
    except Exception:
        return False
    return bool(
        stored.event_id == entry.event_id
        and stored.content_checksum == entry.content_checksum
        and stored.stream_id == entry.stream_id
        and stored.tenant_id == entry.tenant_id
        and stored.stream_sequence == entry.canonical_sequence
        and stored.record_checksum == entry.canonical_record_checksum
        and checksum_for(project_event(stored))
        == entry.canonical_projection_checksum
    )


def _checksum(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name).lower()
    prefix, separator, digest = text.partition(":")
    if (
        separator != ":"
        or prefix != "sha256"
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError(f"{field_name} must be sha256:<64 lowercase hex>")
    return text


def _reason_class(value: Any) -> str:
    text = _required_text(value, "reason_class")
    if len(text) > 128 or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
        for character in text
    ):
        raise ValueError("reason_class must be a bounded lowercase identifier")
    return text


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _optional_integer(value: Any, field_name: str, *, minimum: int) -> None:
    if value is None:
        return
    _integer(value, field_name, minimum=minimum)


def _integer(value: Any, field_name: str, *, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field_name} must be an integer greater than or equal to {minimum}")


def _integer_value(value: Any, field_name: str, *, minimum: int) -> int:
    _integer(value, field_name, minimum=minimum)
    return value


def _utc(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any, field_name: str) -> datetime:
    text = _required_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} is invalid") from error
    return _utc(parsed, field_name)


def _mapping_list(value: Any, field_name: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{field_name} must be an array of objects")
    return list(value)


__all__ = [
    "BACKFILL_REPORT_SCHEMA",
    "SHADOW_REPORT_SCHEMA",
    "EventMigrationBackfill",
    "MigrationBackfillError",
    "MigrationBackfillReport",
    "MigrationBackfillReportStorePort",
    "MigrationBackfillStatus",
    "MigrationImportDisposition",
    "MigrationImportEntry",
    "MigrationResumeError",
    "MigrationShadowComparator",
    "MigrationShadowMismatch",
    "MigrationShadowMismatchError",
    "MigrationShadowReport",
    "MigrationSourceChangedError",
    "migration_records_fingerprint",
    "migration_source_identity",
]
