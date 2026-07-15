from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hmac import compare_digest
from hashlib import sha256
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from framework.events.canonical import (
    BusinessContext,
    EventCandidate,
    ProducerIdentity,
    StoredEvent,
    TraceBlock,
    checksum_for,
    normalize_canonical_json,
    thaw_canonical_json,
)
from framework.events.errors import (
    EventContextConflictError,
    EventQuarantineError,
    EventSecurityError,
    EventUnknownSchemaError,
)
from framework.events.schema import (
    HARNESS_EVENT_ALIASES,
    SUPPORTED_HISTORICAL_ENVELOPE_SCHEMAS,
    EventSchemaCatalog,
    EventSecurityProjector,
    SecurityClassification,
    default_event_schema_catalog,
)
from framework.shared.json import stable_json_dumps


_WORKFLOW_DATA_SCHEMA = "newsroom.workflow-event/v1"
_HARNESS_DATA_SCHEMA = "newsroom.harness-event/v1"
_CANONICAL_ENVELOPE_SCHEMA = "newsroom.event-envelope/v2"
_CURRENT_WORKFLOW_CHECKPOINT_SCHEMA = "workflow-checkpoint/v1"
_SUPPORTED_CHECKPOINT_SCHEMAS = frozenset(
    {
        "newsroom.workflow_checkpoint.v1",
        "workflow-checkpoint/v0",
        _CURRENT_WORKFLOW_CHECKPOINT_SCHEMA,
    }
)
_LEGACY_CONTEXT_FIELDS = (
    "run_id",
    "workflow_id",
    "step_id",
    "task_id",
    "agent_id",
    "tool_call_id",
    "request_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "component",
)
_DOS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


class MigrationSourceKind(StrEnum):
    LEGACY_RUN_JSONL = "legacy_run_jsonl"
    LOCAL_EVENT_RECORD = "local_event_record"
    POSTGRESQL_ROW = "postgresql_row"
    CHECKPOINT = "checkpoint"
    HARNESS_HISTORY = "harness_history"


class MigrationClassification(StrEnum):
    IMPORTABLE = "importable"
    DUPLICATE = "duplicate"
    CONFLICTING = "conflicting"
    UNKNOWN_SCHEMA = "unknown_schema"
    MISSING_TIME = "missing_time"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class MigrationSourceRecord:
    """One detached record read from a migration source.

    Readers represent malformed/non-object input as a typed issue instead of
    carrying raw text.  That keeps reports useful without making error paths a
    second secret-export surface.
    """

    source_kind: MigrationSourceKind | str
    location: str
    value: Mapping[str, Any] | None = None
    issue_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_kind", MigrationSourceKind(self.source_kind))
        location = str(self.location).strip()
        if not location:
            raise ValueError("migration source location is required")
        object.__setattr__(self, "location", location)
        issue = _optional_text(self.issue_reason)
        if (self.value is None) == (issue is None):
            raise ValueError("migration source record requires exactly one value or issue")
        if self.value is not None:
            normalized = normalize_canonical_json(self.value, path="$.migration_source")
            if not isinstance(normalized, Mapping):
                raise TypeError("migration source value must be an object")
            object.__setattr__(self, "value", normalized)
        object.__setattr__(self, "issue_reason", issue)

    @classmethod
    def issue(
        cls,
        source_kind: MigrationSourceKind | str,
        location: str,
        reason: str,
    ) -> MigrationSourceRecord:
        return cls(source_kind=source_kind, location=location, issue_reason=reason)


@dataclass(frozen=True)
class MigrationFinding:
    source_kind: MigrationSourceKind
    location: str
    classification: MigrationClassification
    reason: str
    event_id: str | None = None
    content_checksum: str | None = None

    @property
    def quarantined(self) -> bool:
        return self.classification in {
            MigrationClassification.CONFLICTING,
            MigrationClassification.UNKNOWN_SCHEMA,
            MigrationClassification.MISSING_TIME,
            MigrationClassification.QUARANTINED,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind.value,
            "location": self.location,
            "classification": self.classification.value,
            "reason": self.reason,
            "quarantined": self.quarantined,
            "event_id": self.event_id,
            "content_checksum": self.content_checksum,
        }


@dataclass(frozen=True)
class MigrationSourceSummary:
    source_kind: MigrationSourceKind
    scanned: int
    importable: int
    duplicate: int
    conflicting: int
    unknown_schema: int
    missing_time: int
    quarantined: int
    quarantine_total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind.value,
            "scanned": self.scanned,
            "importable": self.importable,
            "duplicate": self.duplicate,
            "conflicting": self.conflicting,
            "unknown_schema": self.unknown_schema,
            "missing_time": self.missing_time,
            "quarantined": self.quarantined,
            "quarantine_total": self.quarantine_total,
        }


@dataclass(frozen=True)
class MigrationSourceIntegrityEvidence:
    file_count: int
    before_fingerprint: str
    after_fingerprint: str

    def __post_init__(self) -> None:
        if isinstance(self.file_count, bool) or not isinstance(self.file_count, int):
            raise TypeError("migration source file_count must be an integer")
        if self.file_count < 0:
            raise ValueError("migration source file_count must be non-negative")
        for field_name in ("before_fingerprint", "after_fingerprint"):
            fingerprint = _required_text(getattr(self, field_name), field_name)
            if not fingerprint.startswith("sha256:") or len(fingerprint) != 71:
                raise ValueError(f"invalid migration source {field_name}")
            object.__setattr__(self, field_name, fingerprint)

    @property
    def unchanged(self) -> bool:
        return self.before_fingerprint == self.after_fingerprint

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_count": self.file_count,
            "before_fingerprint": self.before_fingerprint,
            "after_fingerprint": self.after_fingerprint,
            "unchanged": self.unchanged,
        }


@dataclass(frozen=True)
class MigrationDryRunReport:
    findings: tuple[MigrationFinding, ...]
    halted: bool = False
    source_integrity: MigrationSourceIntegrityEvidence | None = None

    @property
    def counts(self) -> dict[str, int]:
        return _count_findings(self.findings)

    @property
    def source_summaries(self) -> tuple[MigrationSourceSummary, ...]:
        summaries: list[MigrationSourceSummary] = []
        for source_kind in MigrationSourceKind:
            source_findings = tuple(
                finding for finding in self.findings if finding.source_kind is source_kind
            )
            if not source_findings:
                continue
            counts = _count_findings(source_findings)
            summaries.append(
                MigrationSourceSummary(
                    source_kind=source_kind,
                    scanned=counts["scanned"],
                    importable=counts["importable"],
                    duplicate=counts["duplicate"],
                    conflicting=counts["conflicting"],
                    unknown_schema=counts["unknown_schema"],
                    missing_time=counts["missing_time"],
                    quarantined=counts["quarantined"],
                    quarantine_total=counts["quarantine_total"],
                )
            )
        return tuple(summaries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": True,
            "halted": self.halted,
            "counts": self.counts,
            "sources": [summary.to_dict() for summary in self.source_summaries],
            "findings": [finding.to_dict() for finding in self.findings],
            "source_integrity": (
                self.source_integrity.to_dict()
                if self.source_integrity is not None
                else None
            ),
        }


@dataclass(frozen=True)
class _MappedRecord:
    event_id: str
    content_checksum: str
    identity_namespace: str = "event"

    @property
    def dedupe_key(self) -> str:
        return f"{self.identity_namespace}:{self.event_id}"


class EventMigrationDryRun:
    """Classify legacy event sources without retaining or modifying raw input."""

    def __init__(
        self,
        *,
        schema_catalog: EventSchemaCatalog | None = None,
        security_projector: EventSecurityProjector | None = None,
    ) -> None:
        self._catalog = schema_catalog or default_event_schema_catalog()
        self._security = security_projector or EventSecurityProjector()

    def scan(
        self,
        records: Iterable[MigrationSourceRecord],
        *,
        fail_fast: bool = False,
    ) -> MigrationDryRunReport:
        seen: dict[str, str] = {}
        findings: list[MigrationFinding] = []
        halted = False
        iterator = iter(records)
        try:
            for record in iterator:
                finding = self._classify(record, seen=seen)
                findings.append(finding)
                if fail_fast and finding.quarantined:
                    halted = True
                    break
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                close()
        return MigrationDryRunReport(findings=tuple(findings), halted=halted)

    def _classify(
        self,
        record: MigrationSourceRecord,
        *,
        seen: dict[str, str],
    ) -> MigrationFinding:
        if record.issue_reason is not None:
            return _quarantine_finding(record, record.issue_reason)

        assert record.value is not None
        event_id = _safe_report_id(record.value.get("event_id"))
        try:
            mapped = self._map_record(record)
        except EventQuarantineError as exc:
            return _quarantine_finding(record, exc.reason, event_id=event_id)
        except EventContextConflictError:
            return _quarantine_finding(record, "context_conflict", event_id=event_id)
        except EventUnknownSchemaError:
            return _quarantine_finding(record, "unknown_data_schema", event_id=event_id)
        except EventSecurityError:
            return _quarantine_finding(record, "security_policy_violation", event_id=event_id)
        except (KeyError, TypeError, ValueError):
            return _quarantine_finding(record, "unsupported_legacy_mapping", event_id=event_id)

        existing_checksum = seen.get(mapped.dedupe_key)
        if existing_checksum is None:
            seen[mapped.dedupe_key] = mapped.content_checksum
            return MigrationFinding(
                source_kind=record.source_kind,
                location=record.location,
                classification=MigrationClassification.IMPORTABLE,
                reason="canonical_mapping_ready",
                event_id=mapped.event_id,
                content_checksum=mapped.content_checksum,
            )
        if existing_checksum == mapped.content_checksum:
            return MigrationFinding(
                source_kind=record.source_kind,
                location=record.location,
                classification=MigrationClassification.DUPLICATE,
                reason="same_event_id_same_content",
                event_id=mapped.event_id,
                content_checksum=mapped.content_checksum,
            )
        return MigrationFinding(
            source_kind=record.source_kind,
            location=record.location,
            classification=MigrationClassification.CONFLICTING,
            reason="same_event_id_different_content",
            event_id=mapped.event_id,
            content_checksum=mapped.content_checksum,
        )

    def _map_record(self, record: MigrationSourceRecord) -> _MappedRecord:
        assert record.value is not None
        if record.source_kind is MigrationSourceKind.CHECKPOINT:
            return _map_checkpoint(record.value, source=record.location)
        if record.value.get("envelope_schema") == _CANONICAL_ENVELOPE_SCHEMA:
            return self._map_canonical(record.value, source=record.location)
        return self._map_legacy_event(
            record.value,
            source_kind=record.source_kind,
            source_location=record.location,
        )

    def _map_canonical(
        self,
        value: Mapping[str, Any],
        *,
        source: str,
    ) -> _MappedRecord:
        if not _has_value(value.get("occurred_at")):
            raise EventQuarantineError("missing_occurred_at", source=source)
        _reject_naive_time(
            value.get("occurred_at"),
            source=source,
            reason="invalid_occurred_at",
        )
        if "observed_at" in value:
            _reject_naive_time(
                value.get("observed_at"),
                source=source,
                reason="invalid_observed_at",
            )
        try:
            if "observed_at" in value or "stream_sequence" in value:
                candidate = StoredEvent.from_dict(value, verify_checksum=True).candidate
            else:
                candidate = EventCandidate.from_dict(value, verify_checksum=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise EventQuarantineError("corrupt_record", source=source) from exc

        try:
            registration = self._catalog.get(candidate.event_type, candidate.data_schema)
        except EventUnknownSchemaError as exc:
            raise EventQuarantineError("unknown_data_schema", source=source) from exc
        if candidate.payload is not None:
            self._catalog.validate(
                candidate.event_type,
                candidate.data_schema,
                thaw_canonical_json(candidate.payload),
            )
        projection = self._security.project(
            payload=(
                thaw_canonical_json(candidate.payload)
                if candidate.payload is not None
                else None
            ),
            payload_ref=(candidate.payload_ref.to_dict() if candidate.payload_ref else None),
            extensions=thaw_canonical_json(candidate.extensions),
            policy=registration.sensitivity_policy,
            classification=candidate.security_classification,
            tenant_id=candidate.tenant_id,
        )
        projected_candidate = EventCandidate(
            event_id=candidate.event_id,
            event_type=candidate.event_type,
            data_schema=candidate.data_schema,
            source=candidate.source,
            subject=candidate.subject,
            occurred_at=candidate.occurred_at,
            stream_id=candidate.stream_id,
            correlation_id=candidate.correlation_id,
            causation_id=candidate.causation_id,
            business_context=candidate.business_context,
            producer=candidate.producer,
            trace=candidate.trace,
            tenant_id=projection.tenant_id,
            security_classification=projection.classification,
            content_type=candidate.content_type,
            payload=projection.payload,
            payload_ref=projection.payload_ref,
            extensions=projection.extensions,
        )
        if projected_candidate.content_checksum != candidate.content_checksum:
            raise EventQuarantineError("security_policy_violation", source=source)
        return _MappedRecord(candidate.event_id, candidate.content_checksum)

    def _map_legacy_event(
        self,
        value: Mapping[str, Any],
        *,
        source_kind: MigrationSourceKind,
        source_location: str,
    ) -> _MappedRecord:
        flattened, envelope_schema = _flatten_legacy_envelope(value)
        occurred_at = _first_present(flattened, "occurred_at", "timestamp", "created_at")
        _reject_naive_time(
            occurred_at,
            source=source_location,
            reason="invalid_occurred_at",
        )
        event_type = _required_text(flattened.get("event_type"), "event_type")
        run_id = _optional_text(flattened.get("run_id"))
        if run_id is not None:
            _validate_run_id(run_id)

        data_schema = _data_schema_for(
            flattened,
            source_kind=source_kind,
            event_type=event_type,
        )
        payload = _mapping_or_empty(flattened.get("payload"))
        original_payload = dict(payload)
        payload = _adapt_historical_payload(
            event_type,
            payload,
            flattened=flattened,
            source_kind=source_kind,
        )
        resolved = self._catalog.resolve_historical(
            event_type,
            data_schema,
            payload,
            occurred_at=occurred_at,
            envelope_schema=envelope_schema,
            source=source_location,
        )
        registration = self._catalog.get(resolved.event_type, resolved.data_schema)
        metadata = _mapping_or_empty(flattened.get("metadata"))
        payload_extras = {
            key: item for key, item in original_payload.items() if key not in payload
        }
        extensions = _legacy_extensions(
            flattened,
            metadata=metadata,
            payload_extras=payload_extras,
        )
        classification = flattened.get(
            "security_classification",
            SecurityClassification.INTERNAL.value,
        )
        projection = self._security.project(
            payload=resolved.payload_copy(),
            payload_ref=flattened.get("payload_ref"),
            extensions=extensions,
            policy=registration.sensitivity_policy,
            classification=classification,
            tenant_id=_optional_text(flattened.get("tenant_id")),
        )

        source_name = (
            _optional_text(flattened.get("source"))
            or _optional_text(flattened.get("component"))
            or "legacy-event"
        )
        stream_id = _optional_text(flattened.get("stream_id"))
        if stream_id is None:
            stream_id = f"run:{run_id}" if run_id is not None else f"legacy:{event_type}"
        context = BusinessContext(
            run_id=run_id,
            workflow_id=_optional_text(flattened.get("workflow_id")),
            step_id=_optional_text(flattened.get("step_id")),
            task_id=_optional_text(flattened.get("task_id")),
            agent_id=_optional_text(flattened.get("agent_id")),
            tool_call_id=_optional_text(flattened.get("tool_call_id")),
            request_id=_optional_text(flattened.get("request_id")),
        )
        trace = _trace_block(flattened)
        event_id = _optional_text(flattened.get("event_id"))
        if event_id is None:
            event_id = _derived_event_id(
                source_identity=_stable_source_identity(
                    source_kind=source_kind,
                    source_location=source_location,
                    stream_id=stream_id,
                )
            )
        candidate = EventCandidate(
            event_id=event_id,
            event_type=event_type,
            data_schema=resolved.data_schema,
            source=source_name,
            subject=_optional_text(flattened.get("subject")),
            occurred_at=resolved.occurred_at,
            stream_id=stream_id,
            correlation_id=_optional_text(flattened.get("correlation_id")),
            causation_id=_optional_text(flattened.get("causation_id")),
            business_context=context,
            producer=ProducerIdentity(component=source_name),
            trace=trace,
            tenant_id=projection.tenant_id,
            security_classification=projection.classification,
            content_type=_optional_text(flattened.get("content_type")) or "application/json",
            payload=projection.payload,
            payload_ref=projection.payload_ref,
            extensions=projection.extensions,
        )
        return _MappedRecord(candidate.event_id, candidate.content_checksum)


def _flatten_legacy_envelope(
    value: Mapping[str, Any],
) -> tuple[dict[str, Any], str | None]:
    envelope_schema = _optional_text(
        value.get("envelope_schema", value.get("schema_version"))
    )
    nested = value.get("event")
    if nested is None:
        if (
            envelope_schema is not None
            and envelope_schema not in SUPPORTED_HISTORICAL_ENVELOPE_SCHEMAS
        ):
            raise EventQuarantineError("unknown_envelope_schema")
        return dict(value), envelope_schema
    if not isinstance(nested, Mapping):
        raise TypeError("legacy event envelope event must be an object")
    if envelope_schema not in SUPPORTED_HISTORICAL_ENVELOPE_SCHEMAS:
        raise EventQuarantineError("unknown_envelope_schema")
    nested_schema = _optional_text(nested.get("schema_version"))
    if nested_schema is not None and nested_schema not in SUPPORTED_HISTORICAL_ENVELOPE_SCHEMAS:
        raise EventQuarantineError("unknown_envelope_schema")
    flattened = dict(nested)
    _merge_authoritative_field(
        flattened,
        outer=value.get("event_id"),
        inner=nested.get("event_id"),
        field_name="event_id",
    )
    for field_name in _LEGACY_CONTEXT_FIELDS:
        _merge_authoritative_field(
            flattened,
            outer=value.get(field_name),
            inner=nested.get(field_name),
            field_name=field_name,
        )
    for field_name in (
        "correlation_id",
        "causation_id",
        "sequence",
        "tenant_id",
        "security_classification",
    ):
        _merge_authoritative_field(
            flattened,
            outer=value.get(field_name),
            inner=nested.get(field_name),
            field_name=field_name,
        )
    return flattened, envelope_schema


def _map_checkpoint(value: Mapping[str, Any], *, source: str) -> _MappedRecord:
    flattened = _flatten_checkpoint(value)
    schema = _optional_text(flattened.get("schema_version"))
    if schema is not None and schema not in _SUPPORTED_CHECKPOINT_SCHEMAS:
        raise EventQuarantineError("unknown_data_schema", source=source)
    metadata = _mapping_or_empty(flattened.get("metadata"))
    checkpoint_id = _required_text(flattened.get("checkpoint_id"), "checkpoint_id")
    run_id = _required_text(flattened.get("run_id"), "run_id")
    _validate_run_id(run_id)
    direct_offset = flattened.get("event_offset")
    metadata_offset = metadata.get("event_offset")
    if (
        direct_offset is not None
        and metadata_offset is not None
        and direct_offset != metadata_offset
    ):
        raise EventContextConflictError("event_offset")
    offset = direct_offset if direct_offset is not None else metadata_offset
    if offset is not None and (
        isinstance(offset, bool) or not isinstance(offset, int) or offset < 0
    ):
        raise ValueError("legacy checkpoint event_offset must be non-negative")

    _verify_checkpoint_integrity(flattened, schema=schema, source=source)

    normalized_metadata = dict(metadata)
    normalized_metadata.pop("event_offset", None)
    record_projection = {
        str(key): thaw_canonical_json(item)
        for key, item in flattened.items()
        if key not in {"checksum", "event_offset", "metadata", "payload", "schema_version"}
    }
    if normalized_metadata:
        record_projection["metadata"] = thaw_canonical_json(normalized_metadata)
    projection = {
        "kind": "checkpoint",
        "family": "harness" if isinstance(flattened.get("state"), Mapping) else "workflow",
        "record": record_projection,
        "legacy_event_offset": offset,
    }
    identity = f"checkpoint:{run_id}:{checkpoint_id}"
    return _MappedRecord(identity, checksum_for(projection), identity_namespace="checkpoint")


def _flatten_checkpoint(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = value.get("payload")
    if payload is None:
        return dict(value)
    if not isinstance(payload, Mapping):
        raise TypeError("checkpoint payload must be an object")
    flattened = dict(payload)
    for key, item in value.items():
        if key == "payload":
            continue
        existing = flattened.get(key)
        if _has_value(existing) and _has_value(item) and existing != item:
            raise EventContextConflictError(str(key))
        if _has_value(item) or key not in flattened:
            flattened[key] = item
    return flattened


def _verify_checkpoint_integrity(
    value: Mapping[str, Any],
    *,
    schema: str | None,
    source: str,
) -> None:
    if schema == _CURRENT_WORKFLOW_CHECKPOINT_SCHEMA:
        _verify_workflow_checkpoint_checksum(
            value,
            schema=schema,
            supplied=value.get("checksum"),
            manifest_hash=value.get("manifest_hash"),
            source=source,
        )
        return

    metadata = _mapping_or_empty(value.get("metadata"))
    runtime_only = metadata.get("runtime_only")
    if isinstance(runtime_only, Mapping):
        embedded = runtime_only.get("checkpoint_envelope")
        if isinstance(embedded, Mapping):
            embedded_schema = _required_text(
                embedded.get("schema_version"), "checkpoint schema_version"
            )
            if embedded_schema not in _SUPPORTED_CHECKPOINT_SCHEMAS:
                raise EventQuarantineError("unknown_data_schema", source=source)
            if embedded_schema == _CURRENT_WORKFLOW_CHECKPOINT_SCHEMA:
                _verify_workflow_checkpoint_checksum(
                    value,
                    schema=embedded_schema,
                    supplied=embedded.get("checksum"),
                    manifest_hash=embedded.get("manifest_hash"),
                    source=source,
                )
                return

    state = value.get("state")
    if not isinstance(state, Mapping):
        return
    supplied = _required_text(value.get("checksum"), "checkpoint checksum")
    checksum_payload = {
        "run_id": _required_text(value.get("run_id"), "run_id"),
        "state": thaw_canonical_json(state),
        "last_event_id": _optional_text(value.get("last_event_id")),
    }
    expected = "sha256:" + sha256(
        stable_json_dumps(checksum_payload).encode("utf-8")
    ).hexdigest()
    if not compare_digest(supplied, expected):
        raise EventQuarantineError("checkpoint_checksum_mismatch", source=source)


def _verify_workflow_checkpoint_checksum(
    value: Mapping[str, Any],
    *,
    schema: str,
    supplied: Any,
    manifest_hash: Any,
    source: str,
) -> None:
    actual_checksum = _required_text(supplied, "checkpoint checksum")
    metadata = _mapping_or_empty(value.get("metadata"))
    protected = metadata.get("protected")
    checksum_metadata = (
        {"protected": thaw_canonical_json(protected)}
        if isinstance(protected, Mapping)
        else {}
    )
    checksum_payload = {
        "checkpoint_id": _required_text(value.get("checkpoint_id"), "checkpoint_id"),
        "schema_version": schema,
        "run_id": _required_text(value.get("run_id"), "run_id"),
        "workflow_id": _required_text(value.get("workflow_id"), "workflow_id"),
        "workflow_version": _required_text(value.get("workflow_version"), "workflow_version"),
        "current_step_ids": _required_list(value.get("current_step_ids"), "current_step_ids"),
        "data_buffer_snapshot": _required_mapping_copy(
            value.get("data_buffer_snapshot"), "data_buffer_snapshot"
        ),
        "step_results": _required_mapping_copy(value.get("step_results"), "step_results"),
        "path": _required_list(value.get("path"), "path"),
        "manifest_hash": manifest_hash,
        "created_at": _required_text(value.get("created_at"), "created_at"),
        "metadata": checksum_metadata,
    }
    expected = sha256(stable_json_dumps(checksum_payload).encode("utf-8")).hexdigest()
    if not compare_digest(actual_checksum, expected):
        raise EventQuarantineError("checkpoint_checksum_mismatch", source=source)


def _data_schema_for(
    value: Mapping[str, Any],
    *,
    source_kind: MigrationSourceKind,
    event_type: str,
) -> str:
    explicit = _optional_text(value.get("data_schema"))
    if explicit is not None:
        return explicit
    if source_kind is MigrationSourceKind.HARNESS_HISTORY:
        return _HARNESS_DATA_SCHEMA
    if event_type in HARNESS_EVENT_ALIASES and _looks_like_harness_record(value):
        return _HARNESS_DATA_SCHEMA
    return _WORKFLOW_DATA_SCHEMA


def _looks_like_harness_record(value: Mapping[str, Any]) -> bool:
    return any(
        field_name in value
        for field_name in (
            "decision",
            "retry_count",
            "status_before",
            "status_after",
            "worker_id",
        )
    )


def _adapt_historical_payload(
    event_type: str,
    payload: Mapping[str, Any],
    *,
    flattened: Mapping[str, Any],
    source_kind: MigrationSourceKind,
) -> dict[str, Any]:
    adapted = dict(payload)
    if event_type == "workflow_started" and not adapted.get("run_id"):
        run_id = _optional_text(flattened.get("run_id"))
        if run_id is not None:
            adapted["run_id"] = run_id
    if event_type == "workflow_started":
        for field_name in tuple(adapted):
            if field_name not in {
                "workflow_id",
                "workflow_version",
                "profile",
                "run_id",
                "topic",
            }:
                adapted.pop(field_name)
    if event_type in {"step_succeeded", "step_skipped"}:
        step_id = _optional_text(flattened.get("step_id"))
        if step_id is not None:
            adapted.setdefault("step_id", step_id)
        output_ref = adapted.pop("output_ref", None)
        if "outputs" not in adapted:
            adapted["outputs"] = [output_ref] if _has_value(output_ref) else []
    if event_type == "gate_evaluated" and source_kind is MigrationSourceKind.HARNESS_HISTORY:
        metadata = _mapping_or_empty(flattened.get("metadata"))
        adapted.setdefault("gate", metadata.get("gate") or "legacy-gate")
        adapted.setdefault("details", {})
    return adapted


def _legacy_extensions(
    value: Mapping[str, Any],
    *,
    metadata: Mapping[str, Any],
    payload_extras: Mapping[str, Any],
) -> dict[str, Any]:
    legacy: dict[str, Any] = {}
    if metadata:
        legacy["metadata"] = dict(metadata)
    if payload_extras:
        legacy["payload_extras"] = dict(payload_extras)
    for field_name in ("severity", "redacted"):
        if field_name in value:
            legacy[field_name] = value[field_name]
    trace_id = _optional_text(value.get("trace_id"))
    span_id = _optional_text(value.get("span_id"))
    if trace_id is not None and span_id is None:
        legacy["trace_id"] = trace_id
    return {"io.newsroom.legacy": legacy} if legacy else {}


def _trace_block(value: Mapping[str, Any]) -> TraceBlock | None:
    trace_id = _optional_text(value.get("trace_id"))
    span_id = _optional_text(value.get("span_id"))
    if trace_id is None or span_id is None:
        return None
    is_remote = value.get("is_remote", False)
    if not isinstance(is_remote, bool):
        raise TypeError("legacy trace is_remote must be a boolean")
    return TraceBlock(
        trace_id=trace_id,
        span_id=span_id,
        trace_flags=_optional_text(value.get("trace_flags")) or "00",
        tracestate=_optional_text(value.get("tracestate")),
        is_remote=is_remote,
        parent_span_id=_optional_text(value.get("parent_span_id")),
    )


def _derived_event_id(**projection: Any) -> str:
    digest = sha256(stable_json_dumps(projection).encode("utf-8")).hexdigest()
    return f"migrated-event-{digest[:32]}"


def _stable_source_identity(
    *,
    source_kind: MigrationSourceKind,
    source_location: str,
    stream_id: str,
) -> str:
    """Build a relocation-stable identity for a legacy record without an id.

    JSONL readers expose a 1-based line suffix.  Combining that offset with the
    canonical stream and source kind keeps reruns stable when a corpus root is
    moved while ensuring repeated equal records on different lines remain
    distinct.  PostgreSQL locations are already logical table/key identities
    and contain no DSN.
    """

    location = _required_text(source_location, "source_location")
    if location.startswith("postgresql:"):
        logical_location = location
    else:
        path_part, separator, suffix = location.rpartition(":")
        if separator and suffix.isdigit():
            filename = path_part.replace("\\", "/").rsplit("/", 1)[-1]
            logical_location = (
                f"{stream_id}:file:{filename}:line:{int(suffix)}"
            )
        else:
            filename = location.replace("\\", "/").rsplit("/", 1)[-1]
            logical_location = f"{stream_id}:record:{filename}"
    return f"{source_kind.value}:{logical_location}"


def _merge_authoritative_field(
    target: dict[str, Any],
    *,
    outer: Any,
    inner: Any,
    field_name: str,
) -> None:
    if _has_value(outer) and _has_value(inner) and outer != inner:
        raise EventContextConflictError(field_name)
    if _has_value(outer):
        target[field_name] = outer
    elif _has_value(inner):
        target[field_name] = inner


def _reject_naive_time(value: Any, *, source: str, reason: str) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return
    else:
        return
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EventQuarantineError(reason, source=source)


def _validate_run_id(value: str) -> None:
    if value != value.strip() or not value or any(ord(char) < 32 for char in value):
        raise EventQuarantineError("invalid_stream_identity")
    if any(char in value for char in '<>:"/\\|?*') or value.endswith((".", " ")):
        raise EventQuarantineError("invalid_stream_identity")
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value)
    stem = value.split(".", 1)[0].upper()
    if (
        value in {".", ".."}
        or windows.is_absolute()
        or bool(windows.drive)
        or posix.is_absolute()
        or len(windows.parts) != 1
        or len(posix.parts) != 1
        or stem in _DOS_DEVICE_NAMES
    ):
        raise EventQuarantineError("invalid_stream_identity")


def _quarantine_finding(
    record: MigrationSourceRecord,
    reason: str,
    *,
    event_id: str | None = None,
) -> MigrationFinding:
    normalized_reason = _normalize_reason(reason)
    if normalized_reason in {"unknown_envelope_schema", "unknown_data_schema", "unknown_schema"}:
        classification = MigrationClassification.UNKNOWN_SCHEMA
    elif normalized_reason in {"missing_occurred_at", "missing_time"}:
        classification = MigrationClassification.MISSING_TIME
    elif normalized_reason == "context_conflict":
        classification = MigrationClassification.CONFLICTING
    else:
        classification = MigrationClassification.QUARANTINED
    return MigrationFinding(
        source_kind=record.source_kind,
        location=record.location,
        classification=classification,
        reason=normalized_reason,
        event_id=event_id,
    )


def _normalize_reason(value: str) -> str:
    reason = str(value).strip().lower().replace("-", "_")
    if not reason or len(reason) > 128 or not all(
        char.isalnum() or char == "_" for char in reason
    ):
        return "unsupported_legacy_mapping"
    return reason


def _safe_report_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 256 or any(ord(char) < 32 for char in text):
        return None
    return text


def _count_findings(findings: Iterable[MigrationFinding]) -> dict[str, int]:
    counts = {
        "scanned": 0,
        "importable": 0,
        "duplicate": 0,
        "conflicting": 0,
        "unknown_schema": 0,
        "missing_time": 0,
        "quarantined": 0,
        "quarantine_total": 0,
    }
    for finding in findings:
        counts["scanned"] += 1
        if finding.classification is MigrationClassification.IMPORTABLE:
            counts["importable"] += 1
        elif finding.classification is MigrationClassification.DUPLICATE:
            counts["duplicate"] += 1
        elif finding.classification is MigrationClassification.CONFLICTING:
            counts["conflicting"] += 1
        elif finding.classification is MigrationClassification.UNKNOWN_SCHEMA:
            counts["unknown_schema"] += 1
        elif finding.classification is MigrationClassification.MISSING_TIME:
            counts["missing_time"] += 1
        elif finding.classification is MigrationClassification.QUARANTINED:
            counts["quarantined"] += 1
        if finding.quarantined:
            counts["quarantine_total"] += 1
    return counts


def _first_present(value: Mapping[str, Any], *field_names: str) -> Any:
    for field_name in field_names:
        if _has_value(value.get(field_name)):
            return value[field_name]
    return None


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("legacy mapping field must be an object")
    return dict(value)


def _required_mapping_copy(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return thaw_canonical_json(value)


def _required_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an array")
    return [thaw_canonical_json(item) for item in value]


def _has_value(value: Any) -> bool:
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("optional migration field must be a string")
    text = value.strip()
    return text or None


def _required_text(value: Any, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field_name} is required")
    return text


__all__ = [
    "EventMigrationDryRun",
    "MigrationClassification",
    "MigrationDryRunReport",
    "MigrationFinding",
    "MigrationSourceKind",
    "MigrationSourceIntegrityEvidence",
    "MigrationSourceRecord",
    "MigrationSourceSummary",
]
