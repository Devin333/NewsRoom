from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from framework.events.canonical import (
    CanonicalValue,
    PayloadReference,
    canonical_json_bytes,
    checksum_for,
    normalize_canonical_json,
    thaw_canonical_json,
)
from framework.events.errors import EventIncompleteHistoryError, EventReplayError
from framework.events.schema.security import SecurityClassification
from framework.shared.time import ensure_utc, format_datetime, parse_datetime


REPLAY_ACTIVITY_RECORD_SCHEMA = "newsroom.replay-activity-record/v1"
REPLAY_ACTIVITY_RECORD_CONTENT_TYPE = (
    "application/vnd.newsroom.replay-activity-record+json"
)
REPLAY_ACTIVITY_PAYLOAD_CONTENT_TYPE = "application/json"


class ReplayActivityKind(StrEnum):
    LLM = "llm"
    TOOL = "tool"
    MCP = "mcp"
    HTTP = "http"
    RETRIEVAL = "retrieval"
    MEMORY_WRITE = "memory_write"
    PUBLICATION = "publication"
    EMAIL = "email"
    CLOCK = "clock"
    RANDOM = "random"
    EXTERNAL_DATABASE = "external_database"


class ReplayActivityStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReplayActivityPayloadRole(StrEnum):
    INPUT = "input"
    OUTPUT = "output"
    ERROR = "error"


class ReplayActivityResolutionError(EventReplayError):
    """Base class for recorded-only activity resolution failures."""


class ReplayActivityMissingError(
    EventIncompleteHistoryError, ReplayActivityResolutionError
):
    """The required recorded activity or payload reference does not exist."""


class ReplayActivityIncompleteError(
    EventIncompleteHistoryError, ReplayActivityResolutionError
):
    """The recorded activity has no terminal reusable outcome."""


class ReplayActivityFailedError(
    EventIncompleteHistoryError, ReplayActivityResolutionError
):
    """The historical activity failed and therefore has no successful output to reuse."""


class ReplayActivityCorruptionError(ReplayActivityResolutionError):
    """Recorded activity bytes or checksums violate the immutable contract."""


class ReplayActivityMismatchError(ReplayActivityResolutionError):
    """Recorded activity identity or accepted input differs from replay expectation."""


class ReplayActivityInputMismatchError(ReplayActivityMismatchError):
    """The recorded accepted input does not match the replay command."""


class ReplayActivityTenantMismatchError(ReplayActivityMismatchError):
    """The recorded activity crosses the expected tenant or classification scope."""


class ReplayActivityVersionError(ReplayActivityResolutionError):
    """An exact historical activity contract/handler version is unavailable."""


class ReplayActivityRecordingError(EventReplayError):
    """A durable activity write could not preserve the recording contract."""


class ReplayActivityRecordingConflictError(ReplayActivityRecordingError):
    """An activity identity or state was reused with conflicting durable data."""


@dataclass(frozen=True, slots=True)
class ReplayActivityHandlerVersion:
    activity_kind: ReplayActivityKind | str
    contract_version: str
    handler_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "activity_kind", ReplayActivityKind(self.activity_kind)
        )
        object.__setattr__(
            self,
            "contract_version",
            _required_text(self.contract_version, "contract_version"),
        )
        object.__setattr__(
            self,
            "handler_version",
            _required_text(self.handler_version, "handler_version"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "activity_kind": self.activity_kind.value,
            "contract_version": self.contract_version,
            "handler_version": self.handler_version,
        }


@dataclass(frozen=True, slots=True)
class ReplayActivityDescriptor:
    activity_id: str
    activity_kind: ReplayActivityKind | str
    input_ref: PayloadReference
    input_checksum: str
    idempotency_key: str
    attempt: int
    contract_version: str
    handler_version: str
    accepted_at: datetime
    context: Mapping[str, CanonicalValue] = field(default_factory=dict)
    tenant_id: str | None = None
    security_classification: SecurityClassification | str = (
        SecurityClassification.INTERNAL
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "activity_id", _required_text(self.activity_id, "activity_id")
        )
        object.__setattr__(
            self, "activity_kind", ReplayActivityKind(self.activity_kind)
        )
        if not isinstance(self.input_ref, PayloadReference):
            raise TypeError("input_ref must be PayloadReference")
        input_checksum = _checksum(self.input_checksum, "input_checksum")
        if input_checksum != self.input_ref.expected_checksum:
            raise ValueError("input_checksum must match input_ref.expected_checksum")
        object.__setattr__(self, "input_checksum", input_checksum)
        object.__setattr__(
            self,
            "idempotency_key",
            _required_text(self.idempotency_key, "idempotency_key"),
        )
        object.__setattr__(self, "attempt", _positive_int(self.attempt, "attempt"))
        object.__setattr__(
            self,
            "contract_version",
            _required_text(self.contract_version, "contract_version"),
        )
        object.__setattr__(
            self,
            "handler_version",
            _required_text(self.handler_version, "handler_version"),
        )
        object.__setattr__(
            self, "accepted_at", _datetime(self.accepted_at, "accepted_at")
        )
        context = normalize_canonical_json(
            self.context,
            path="$.replay_activity.context",
        )
        if not isinstance(context, Mapping):
            raise TypeError("context must be an object")
        object.__setattr__(self, "context", context)
        object.__setattr__(
            self, "tenant_id", _optional_text(self.tenant_id, "tenant_id")
        )
        object.__setattr__(
            self,
            "security_classification",
            SecurityClassification(self.security_classification),
        )

    @property
    def pinned_version(self) -> ReplayActivityHandlerVersion:
        return ReplayActivityHandlerVersion(
            self.activity_kind,
            self.contract_version,
            self.handler_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "activity_kind": self.activity_kind.value,
            "input_ref": self.input_ref.to_dict(),
            "input_checksum": self.input_checksum,
            "idempotency_key": self.idempotency_key,
            "attempt": self.attempt,
            "contract_version": self.contract_version,
            "handler_version": self.handler_version,
            "accepted_at": format_datetime(self.accepted_at),
            "context": thaw_canonical_json(self.context),
            "tenant_id": self.tenant_id,
            "security_classification": self.security_classification.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ReplayActivityDescriptor:
        _reject_unknown_fields(
            value,
            {
                "activity_id",
                "activity_kind",
                "input_ref",
                "input_checksum",
                "idempotency_key",
                "attempt",
                "contract_version",
                "handler_version",
                "accepted_at",
                "context",
                "tenant_id",
                "security_classification",
            },
            "activity",
        )
        input_ref = value.get("input_ref")
        if not isinstance(input_ref, Mapping):
            raise ValueError("input_ref must be an object")
        accepted_at = parse_datetime(value.get("accepted_at"))
        if accepted_at is None:
            raise ValueError("accepted_at must be a datetime")
        return cls(
            activity_id=value.get("activity_id"),
            activity_kind=value.get("activity_kind"),
            input_ref=PayloadReference.from_dict(input_ref),
            input_checksum=value.get("input_checksum"),
            idempotency_key=value.get("idempotency_key"),
            attempt=value.get("attempt"),
            contract_version=value.get("contract_version"),
            handler_version=value.get("handler_version"),
            accepted_at=accepted_at,
            context=_mapping(value.get("context", {}), "context"),
            tenant_id=value.get("tenant_id"),
            security_classification=value.get("security_classification"),
        )


@dataclass(frozen=True, slots=True)
class ReplayActivityOutcome:
    activity_id: str
    status: ReplayActivityStatus | str
    started_at: datetime
    completed_at: datetime | None = None
    output_ref: PayloadReference | None = None
    output_checksum: str | None = None
    error_class: str | None = None
    error_ref: PayloadReference | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "activity_id", _required_text(self.activity_id, "activity_id")
        )
        status = ReplayActivityStatus(self.status)
        object.__setattr__(self, "status", status)
        started_at = _datetime(self.started_at, "started_at")
        object.__setattr__(self, "started_at", started_at)
        completed_at = (
            None
            if self.completed_at is None
            else _datetime(self.completed_at, "completed_at")
        )
        if completed_at is not None and completed_at < started_at:
            raise ValueError("completed_at cannot precede started_at")
        object.__setattr__(self, "completed_at", completed_at)
        if self.output_ref is not None and not isinstance(
            self.output_ref, PayloadReference
        ):
            raise TypeError("output_ref must be PayloadReference")
        output_checksum = (
            None
            if self.output_checksum is None
            else _checksum(self.output_checksum, "output_checksum")
        )
        if (
            self.output_ref is not None
            and output_checksum != self.output_ref.expected_checksum
        ):
            raise ValueError("output_checksum must match output_ref.expected_checksum")
        object.__setattr__(self, "output_checksum", output_checksum)
        if self.error_ref is not None and not isinstance(
            self.error_ref, PayloadReference
        ):
            raise TypeError("error_ref must be PayloadReference")
        error_class = _optional_text(self.error_class, "error_class")
        object.__setattr__(self, "error_class", error_class)
        if status is ReplayActivityStatus.PENDING:
            if any(
                value is not None
                for value in (
                    completed_at,
                    self.output_ref,
                    output_checksum,
                    error_class,
                    self.error_ref,
                )
            ):
                raise ValueError(
                    "pending activity cannot contain terminal outcome fields"
                )
        elif status is ReplayActivityStatus.SUCCEEDED:
            if (
                completed_at is None
                or self.output_ref is None
                or output_checksum is None
            ):
                raise ValueError(
                    "succeeded activity requires completed_at and output reference"
                )
            if error_class is not None or self.error_ref is not None:
                raise ValueError("succeeded activity cannot contain error fields")
        else:
            if completed_at is None or error_class is None:
                raise ValueError(
                    "failed activity requires completed_at and error_class"
                )
            if self.output_ref is not None or output_checksum is not None:
                raise ValueError("failed activity cannot contain output fields")

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "status": self.status.value,
            "started_at": format_datetime(self.started_at),
            "completed_at": format_datetime(self.completed_at),
            "output_ref": None
            if self.output_ref is None
            else self.output_ref.to_dict(),
            "output_checksum": self.output_checksum,
            "error_class": self.error_class,
            "error_ref": None if self.error_ref is None else self.error_ref.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ReplayActivityOutcome:
        _reject_unknown_fields(
            value,
            {
                "activity_id",
                "status",
                "started_at",
                "completed_at",
                "output_ref",
                "output_checksum",
                "error_class",
                "error_ref",
            },
            "outcome",
        )
        output_ref = value.get("output_ref")
        error_ref = value.get("error_ref")
        started_at = parse_datetime(value.get("started_at"))
        completed_at = parse_datetime(value.get("completed_at"))
        if started_at is None:
            raise ValueError("started_at must be a datetime")
        return cls(
            activity_id=value.get("activity_id"),
            status=value.get("status"),
            started_at=started_at,
            completed_at=completed_at,
            output_ref=(
                None
                if output_ref is None
                else PayloadReference.from_dict(_mapping(output_ref, "output_ref"))
            ),
            output_checksum=value.get("output_checksum"),
            error_class=value.get("error_class"),
            error_ref=(
                None
                if error_ref is None
                else PayloadReference.from_dict(_mapping(error_ref, "error_ref"))
            ),
        )


@dataclass(frozen=True, slots=True)
class ReplayActivityRecord:
    activity: ReplayActivityDescriptor
    outcome: ReplayActivityOutcome
    schema: str = REPLAY_ACTIVITY_RECORD_SCHEMA
    record_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.activity, ReplayActivityDescriptor):
            raise TypeError("activity must be ReplayActivityDescriptor")
        if not isinstance(self.outcome, ReplayActivityOutcome):
            raise TypeError("outcome must be ReplayActivityOutcome")
        if self.activity.activity_id != self.outcome.activity_id:
            raise ValueError("activity and outcome identity must match")
        schema = _required_text(self.schema, "schema")
        if schema != REPLAY_ACTIVITY_RECORD_SCHEMA:
            raise ValueError("unsupported replay activity record schema")
        object.__setattr__(self, "schema", schema)
        object.__setattr__(
            self, "record_checksum", checksum_for(self.checksum_projection())
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "activity": self.activity.to_dict(),
            "outcome": self.outcome.to_dict(),
        }

    def verify_integrity(self) -> None:
        if checksum_for(self.checksum_projection()) != self.record_checksum:
            raise ReplayActivityCorruptionError(
                "recorded activity checksum does not match"
            )

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "record_checksum": self.record_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ReplayActivityRecord:
        try:
            normalized = normalize_canonical_json(
                value, path="$.replay_activity_record"
            )
            raw = thaw_canonical_json(normalized)
            if not isinstance(raw, Mapping):
                raise ValueError("activity record must be an object")
            _reject_unknown_fields(
                raw,
                {"schema", "activity", "outcome", "record_checksum"},
                "activity record",
            )
            record = cls(
                schema=raw.get("schema"),
                activity=ReplayActivityDescriptor.from_dict(
                    _mapping(raw.get("activity"), "activity")
                ),
                outcome=ReplayActivityOutcome.from_dict(
                    _mapping(raw.get("outcome"), "outcome")
                ),
            )
            supplied = _checksum(raw.get("record_checksum"), "record_checksum")
            if supplied != record.record_checksum:
                raise ReplayActivityCorruptionError(
                    "recorded activity checksum does not match"
                )
            return record
        except ReplayActivityCorruptionError:
            raise
        except Exception as exc:
            raise ReplayActivityCorruptionError(
                "recorded activity contract is corrupt"
            ) from exc


@dataclass(frozen=True, slots=True)
class ReplayActivityPayload:
    """Canonical payload snapshot written independently from an activity record."""

    activity_id: str
    activity_kind: ReplayActivityKind | str
    role: ReplayActivityPayloadRole | str
    content: CanonicalValue
    idempotency_key: str
    attempt: int
    contract_version: str
    handler_version: str
    tenant_id: str | None = None
    security_classification: SecurityClassification | str = (
        SecurityClassification.INTERNAL
    )
    content_type: str = REPLAY_ACTIVITY_PAYLOAD_CONTENT_TYPE
    content_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "activity_id", _required_text(self.activity_id, "activity_id")
        )
        object.__setattr__(
            self, "activity_kind", ReplayActivityKind(self.activity_kind)
        )
        object.__setattr__(self, "role", ReplayActivityPayloadRole(self.role))
        content = normalize_canonical_json(
            self.content,
            path=f"$.replay_activity_payload.{self.role.value}",
        )
        object.__setattr__(self, "content", content)
        object.__setattr__(
            self,
            "idempotency_key",
            _required_text(self.idempotency_key, "idempotency_key"),
        )
        object.__setattr__(self, "attempt", _positive_int(self.attempt, "attempt"))
        object.__setattr__(
            self,
            "contract_version",
            _required_text(self.contract_version, "contract_version"),
        )
        object.__setattr__(
            self,
            "handler_version",
            _required_text(self.handler_version, "handler_version"),
        )
        object.__setattr__(
            self, "tenant_id", _optional_text(self.tenant_id, "tenant_id")
        )
        object.__setattr__(
            self,
            "security_classification",
            SecurityClassification(self.security_classification),
        )
        object.__setattr__(
            self,
            "content_type",
            _required_text(self.content_type, "content_type"),
        )
        object.__setattr__(self, "content_checksum", checksum_for(content))

    @property
    def pinned_version(self) -> ReplayActivityHandlerVersion:
        return ReplayActivityHandlerVersion(
            self.activity_kind,
            self.contract_version,
            self.handler_version,
        )


@dataclass(frozen=True, slots=True)
class RecordedActivityPayloadWrite:
    payload: ReplayActivityPayload
    payload_ref: PayloadReference

    def __post_init__(self) -> None:
        if not isinstance(self.payload, ReplayActivityPayload):
            raise TypeError("payload must be ReplayActivityPayload")
        if not isinstance(self.payload_ref, PayloadReference):
            raise TypeError("payload_ref must be PayloadReference")
        self.verify_integrity()

    def verify_integrity(self) -> None:
        if self.payload_ref.expected_checksum != self.payload.content_checksum:
            raise ReplayActivityCorruptionError(
                "recorded activity payload reference checksum does not match"
            )
        if self.payload_ref.content_type != self.payload.content_type:
            raise ReplayActivityCorruptionError(
                "recorded activity payload reference content type does not match"
            )
        expected_size = len(canonical_json_bytes(self.payload.content))
        if (
            self.payload_ref.size_bytes is not None
            and self.payload_ref.size_bytes != expected_size
        ):
            raise ReplayActivityCorruptionError(
                "recorded activity payload reference size does not match"
            )


@dataclass(frozen=True, slots=True)
class RecordedActivityWrite:
    record: ReplayActivityRecord
    recorded_ref: PayloadReference

    def __post_init__(self) -> None:
        if not isinstance(self.record, ReplayActivityRecord):
            raise TypeError("record must be ReplayActivityRecord")
        if not isinstance(self.recorded_ref, PayloadReference):
            raise TypeError("recorded_ref must be PayloadReference")
        self.verify_integrity()

    def verify_integrity(self) -> None:
        self.record.verify_integrity()
        if self.recorded_ref.expected_checksum != self.record.record_checksum:
            raise ReplayActivityCorruptionError(
                "recorded activity write reference checksum does not match"
            )
        if self.recorded_ref.content_type != REPLAY_ACTIVITY_RECORD_CONTENT_TYPE:
            raise ReplayActivityCorruptionError(
                "recorded activity write reference content type does not match"
            )
        expected_size = len(canonical_json_bytes(self.record.to_dict()))
        if (
            self.recorded_ref.size_bytes is not None
            and self.recorded_ref.size_bytes != expected_size
        ):
            raise ReplayActivityCorruptionError(
                "recorded activity write reference size does not match"
            )


class ReplayActivityRegistry:
    """Exact version registry for historical activity handlers.

    Registrations describe compatibility only. They intentionally contain no
    callable, provider, transport, or other live-operation capability.
    """

    def __init__(self) -> None:
        self._versions: dict[
            tuple[ReplayActivityKind, str, str], ReplayActivityHandlerVersion
        ] = {}

    def register(self, version: ReplayActivityHandlerVersion) -> None:
        if not isinstance(version, ReplayActivityHandlerVersion):
            raise TypeError("version must be ReplayActivityHandlerVersion")
        key = (version.activity_kind, version.contract_version, version.handler_version)
        if key in self._versions:
            raise ReplayActivityVersionError(
                "duplicate replay activity version: "
                f"{version.activity_kind.value} {version.contract_version} "
                f"{version.handler_version}"
            )
        self._versions[key] = version

    def resolve(
        self,
        activity_kind: ReplayActivityKind | str,
        contract_version: str,
        handler_version: str,
    ) -> ReplayActivityHandlerVersion:
        key = (
            ReplayActivityKind(activity_kind),
            _required_text(contract_version, "contract_version"),
            _required_text(handler_version, "handler_version"),
        )
        try:
            return self._versions[key]
        except KeyError as exc:
            raise ReplayActivityVersionError(
                "unregistered replay activity version: "
                f"{key[0].value} {key[1]} {key[2]}"
            ) from exc

    def versions(self) -> tuple[ReplayActivityHandlerVersion, ...]:
        return tuple(
            self._versions[key]
            for key in sorted(
                self._versions, key=lambda item: (item[0].value, item[1], item[2])
            )
        )


@runtime_checkable
class RecordedActivityStorePort(Protocol):
    def put_payload(
        self,
        payload: ReplayActivityPayload,
        *,
        tenant_id: str | None,
        classification: SecurityClassification,
    ) -> RecordedActivityPayloadWrite:
        """Persist one immutable payload before it is referenced by a record.

        Implementations must key writes by activity identity and payload role.
        An exact retry returns the original write; any identity, version, scope,
        content, or checksum conflict must fail without replacing stored bytes.
        """
        ...

    def accept_record(
        self,
        record: ReplayActivityRecord,
        *,
        tenant_id: str | None,
        classification: SecurityClassification,
    ) -> RecordedActivityWrite:
        """Put the pending activity before live work starts.

        The write is idempotent for an identical descriptor. If an identical
        activity is already terminal, the current terminal write is returned.
        Any conflicting descriptor must fail closed.
        """
        ...

    def complete_record(
        self,
        accepted_ref: PayloadReference,
        record: ReplayActivityRecord,
        *,
        tenant_id: str | None,
        classification: SecurityClassification,
    ) -> RecordedActivityWrite:
        """Compare-and-set a pending activity to one immutable terminal record.

        An uncertain-commit retry for the exact terminal record returns the
        committed write. A stale reference or different terminal outcome must
        fail without replacing the accepted or completed record.
        """
        ...

    def get_record(
        self,
        recorded_ref: PayloadReference,
        *,
        tenant_id: str | None,
    ) -> ReplayActivityRecord | Mapping[str, Any] | None:
        """Read one immutable historical activity. No live fallback is permitted."""
        ...

    def get_payload(
        self,
        payload_ref: PayloadReference,
        *,
        tenant_id: str | None,
    ) -> CanonicalValue:
        """Resolve one integrity-bound recorded payload without live fallback."""
        ...


class ActivityRecorder:
    """Create durable activity records without owning or invoking live providers."""

    __slots__ = ("_store",)

    def __init__(self, store: RecordedActivityStorePort) -> None:
        if store is None:
            raise TypeError("store is required")
        self._store = store

    def accept(
        self,
        *,
        activity_id: str,
        activity_kind: ReplayActivityKind | str,
        input_value: Any,
        idempotency_key: str,
        attempt: int,
        contract_version: str,
        handler_version: str,
        accepted_at: datetime,
        started_at: datetime,
        context: Mapping[str, CanonicalValue] | None = None,
        tenant_id: str | None = None,
        security_classification: SecurityClassification
        | str = SecurityClassification.INTERNAL,
        input_content_type: str = REPLAY_ACTIVITY_PAYLOAD_CONTENT_TYPE,
    ) -> ActivityRecordingHandle:
        normalized_accepted_at = _datetime(accepted_at, "accepted_at")
        normalized_started_at = _datetime(started_at, "started_at")
        if normalized_started_at < normalized_accepted_at:
            raise ValueError("started_at cannot precede accepted_at")
        classification = SecurityClassification(security_classification)
        normalized_context = normalize_canonical_json(
            {} if context is None else context,
            path="$.replay_activity.context",
        )
        if not isinstance(normalized_context, Mapping):
            raise TypeError("context must be an object")
        input_payload = ReplayActivityPayload(
            activity_id=activity_id,
            activity_kind=activity_kind,
            role=ReplayActivityPayloadRole.INPUT,
            content=input_value,
            idempotency_key=idempotency_key,
            attempt=attempt,
            contract_version=contract_version,
            handler_version=handler_version,
            tenant_id=tenant_id,
            security_classification=classification,
            content_type=input_content_type,
        )
        input_write = self._store.put_payload(
            input_payload,
            tenant_id=input_payload.tenant_id,
            classification=input_payload.security_classification,
        )
        _validate_payload_write(input_payload, input_write)
        activity = ReplayActivityDescriptor(
            activity_id=input_payload.activity_id,
            activity_kind=input_payload.activity_kind,
            input_ref=input_write.payload_ref,
            input_checksum=input_payload.content_checksum,
            idempotency_key=input_payload.idempotency_key,
            attempt=input_payload.attempt,
            contract_version=input_payload.contract_version,
            handler_version=input_payload.handler_version,
            accepted_at=normalized_accepted_at,
            context=normalized_context,
            tenant_id=input_payload.tenant_id,
            security_classification=input_payload.security_classification,
        )
        pending_record = ReplayActivityRecord(
            activity=activity,
            outcome=ReplayActivityOutcome(
                activity_id=activity.activity_id,
                status=ReplayActivityStatus.PENDING,
                started_at=normalized_started_at,
            ),
        )
        accepted_write = self._store.accept_record(
            pending_record,
            tenant_id=activity.tenant_id,
            classification=activity.security_classification,
        )
        accepted_write = _validate_accepted_write(pending_record, accepted_write)
        return ActivityRecordingHandle(self._store, accepted_write)


class ActivityRecordingHandle:
    """Stateful completion handle for one accepted durable activity."""

    __slots__ = ("_store", "_write")

    def __init__(
        self,
        store: RecordedActivityStorePort,
        accepted_write: RecordedActivityWrite,
    ) -> None:
        if store is None:
            raise TypeError("store is required")
        if not isinstance(accepted_write, RecordedActivityWrite):
            raise TypeError("accepted_write must be RecordedActivityWrite")
        accepted_write.verify_integrity()
        _validate_independent_terminal_reference(accepted_write)
        self._store = store
        self._write = accepted_write

    @property
    def activity(self) -> ReplayActivityDescriptor:
        return self._write.record.activity

    @property
    def outcome(self) -> ReplayActivityOutcome:
        return self._write.record.outcome

    @property
    def recorded_ref(self) -> PayloadReference:
        return self._write.recorded_ref

    @property
    def is_terminal(self) -> bool:
        return self.outcome.status is not ReplayActivityStatus.PENDING

    def succeed(
        self,
        output: Any,
        *,
        completed_at: datetime,
        content_type: str = REPLAY_ACTIVITY_PAYLOAD_CONTENT_TYPE,
    ) -> RecordedActivityWrite:
        if self.outcome.status is ReplayActivityStatus.FAILED:
            raise ReplayActivityRecordingConflictError(
                "failed activity cannot be completed as succeeded"
            )
        payload = self._completion_payload(
            ReplayActivityPayloadRole.OUTPUT,
            output,
            content_type,
        )
        if self.outcome.status is ReplayActivityStatus.SUCCEEDED:
            self._validate_success_retry(payload)
            return self._write
        completed_at = _datetime(completed_at, "completed_at")
        if completed_at < self.outcome.started_at:
            raise ValueError("completed_at cannot precede started_at")
        payload_write = self._store.put_payload(
            payload,
            tenant_id=payload.tenant_id,
            classification=payload.security_classification,
        )
        _validate_payload_write(payload, payload_write)
        terminal_record = ReplayActivityRecord(
            activity=self.activity,
            outcome=ReplayActivityOutcome(
                activity_id=self.activity.activity_id,
                status=ReplayActivityStatus.SUCCEEDED,
                started_at=self.outcome.started_at,
                completed_at=completed_at,
                output_ref=payload_write.payload_ref,
                output_checksum=payload.content_checksum,
            ),
        )
        self._write = self._complete(terminal_record)
        return self._write

    def fail(
        self,
        error_class: str,
        error: Any,
        *,
        completed_at: datetime,
        content_type: str = REPLAY_ACTIVITY_PAYLOAD_CONTENT_TYPE,
    ) -> RecordedActivityWrite:
        normalized_error_class = _required_text(error_class, "error_class")
        if self.outcome.status is ReplayActivityStatus.SUCCEEDED:
            raise ReplayActivityRecordingConflictError(
                "succeeded activity cannot be completed as failed"
            )
        payload = self._completion_payload(
            ReplayActivityPayloadRole.ERROR,
            error,
            content_type,
        )
        if self.outcome.status is ReplayActivityStatus.FAILED:
            self._validate_failure_retry(normalized_error_class, payload)
            return self._write
        completed_at = _datetime(completed_at, "completed_at")
        if completed_at < self.outcome.started_at:
            raise ValueError("completed_at cannot precede started_at")
        payload_write = self._store.put_payload(
            payload,
            tenant_id=payload.tenant_id,
            classification=payload.security_classification,
        )
        _validate_payload_write(payload, payload_write)
        terminal_record = ReplayActivityRecord(
            activity=self.activity,
            outcome=ReplayActivityOutcome(
                activity_id=self.activity.activity_id,
                status=ReplayActivityStatus.FAILED,
                started_at=self.outcome.started_at,
                completed_at=completed_at,
                error_class=normalized_error_class,
                error_ref=payload_write.payload_ref,
            ),
        )
        self._write = self._complete(terminal_record)
        return self._write

    def _completion_payload(
        self,
        role: ReplayActivityPayloadRole,
        content: Any,
        content_type: str,
    ) -> ReplayActivityPayload:
        activity = self.activity
        return ReplayActivityPayload(
            activity_id=activity.activity_id,
            activity_kind=activity.activity_kind,
            role=role,
            content=content,
            idempotency_key=activity.idempotency_key,
            attempt=activity.attempt,
            contract_version=activity.contract_version,
            handler_version=activity.handler_version,
            tenant_id=activity.tenant_id,
            security_classification=activity.security_classification,
            content_type=content_type,
        )

    def _complete(self, terminal_record: ReplayActivityRecord) -> RecordedActivityWrite:
        completed_write = self._store.complete_record(
            self.recorded_ref,
            terminal_record,
            tenant_id=self.activity.tenant_id,
            classification=self.activity.security_classification,
        )
        return _validate_completed_write(terminal_record, completed_write)

    def _validate_success_retry(self, payload: ReplayActivityPayload) -> None:
        output_ref = self.outcome.output_ref
        if (
            output_ref is None
            or self.outcome.output_checksum != payload.content_checksum
            or output_ref.content_type != payload.content_type
        ):
            raise ReplayActivityRecordingConflictError(
                "succeeded activity was retried with conflicting output"
            )

    def _validate_failure_retry(
        self,
        error_class: str,
        payload: ReplayActivityPayload,
    ) -> None:
        error_ref = self.outcome.error_ref
        if (
            self.outcome.error_class != error_class
            or error_ref is None
            or error_ref.expected_checksum != payload.content_checksum
            or error_ref.content_type != payload.content_type
        ):
            raise ReplayActivityRecordingConflictError(
                "failed activity was retried with conflicting error"
            )


@dataclass(frozen=True, slots=True)
class ResolvedReplayActivity:
    activity: ReplayActivityDescriptor
    outcome: ReplayActivityOutcome
    pinned_version: ReplayActivityHandlerVersion
    recorded_ref: PayloadReference

    def __post_init__(self) -> None:
        if self.activity.activity_id != self.outcome.activity_id:
            raise ValueError("resolved activity and outcome identity must match")
        if self.activity.pinned_version != self.pinned_version:
            raise ValueError("resolved activity version does not match pinned version")


@runtime_checkable
class ReplayActivityResolverPort(Protocol):
    def resolve(
        self,
        expected_activity: ReplayActivityDescriptor,
        recorded_ref: PayloadReference,
    ) -> ResolvedReplayActivity:
        """Resolve one recorded result without exposing a live operation."""
        ...


class RecordedActivityResolver:
    """Resolve only integrity-bound recorded outcomes; never invoke live work."""

    __slots__ = ("_store", "_registry")

    def __init__(
        self,
        store: RecordedActivityStorePort,
        registry: ReplayActivityRegistry,
    ) -> None:
        if store is None:
            raise TypeError("store is required")
        if not isinstance(registry, ReplayActivityRegistry):
            raise TypeError("registry must be ReplayActivityRegistry")
        self._store = store
        self._registry = registry

    def resolve(
        self,
        expected_activity: ReplayActivityDescriptor,
        recorded_ref: PayloadReference,
    ) -> ResolvedReplayActivity:
        if not isinstance(expected_activity, ReplayActivityDescriptor):
            raise TypeError("expected_activity must be ReplayActivityDescriptor")
        if not isinstance(recorded_ref, PayloadReference):
            raise TypeError("recorded_ref must be PayloadReference")
        pinned_version = self._registry.resolve(
            expected_activity.activity_kind,
            expected_activity.contract_version,
            expected_activity.handler_version,
        )
        try:
            stored = self._store.get_record(
                recorded_ref,
                tenant_id=expected_activity.tenant_id,
            )
        except ReplayActivityResolutionError:
            raise
        except Exception as exc:
            raise ReplayActivityMissingError(
                "recorded activity is unavailable"
            ) from exc
        if stored is None:
            raise ReplayActivityMissingError("recorded activity is missing")
        if isinstance(stored, Mapping):
            record = ReplayActivityRecord.from_dict(stored)
        elif isinstance(stored, ReplayActivityRecord):
            record = stored
            record.verify_integrity()
        else:
            raise ReplayActivityCorruptionError(
                "recorded activity store returned invalid data"
            )
        if record.record_checksum != recorded_ref.expected_checksum:
            raise ReplayActivityCorruptionError(
                "recorded activity reference checksum does not match"
            )
        actual = record.activity
        if actual.tenant_id != expected_activity.tenant_id:
            raise ReplayActivityTenantMismatchError(
                "recorded activity tenant does not match"
            )
        if (
            actual.security_classification
            is not expected_activity.security_classification
        ):
            raise ReplayActivityTenantMismatchError(
                "recorded activity classification does not match"
            )
        if actual.pinned_version != expected_activity.pinned_version:
            raise ReplayActivityVersionError("recorded activity version does not match")
        if actual.activity_id != expected_activity.activity_id:
            raise ReplayActivityMismatchError(
                "recorded activity identity does not match"
            )
        if (
            actual.input_ref != expected_activity.input_ref
            or actual.input_checksum != expected_activity.input_checksum
            or actual.idempotency_key != expected_activity.idempotency_key
            or actual.attempt != expected_activity.attempt
        ):
            raise ReplayActivityInputMismatchError(
                "recorded activity accepted input does not match"
            )
        if record.outcome.status is ReplayActivityStatus.PENDING:
            raise ReplayActivityIncompleteError("recorded activity result is pending")
        return ResolvedReplayActivity(
            activity=actual,
            outcome=record.outcome,
            pinned_version=pinned_version,
            recorded_ref=recorded_ref,
        )


def _validate_payload_write(
    expected: ReplayActivityPayload,
    actual: Any,
) -> RecordedActivityPayloadWrite:
    if not isinstance(actual, RecordedActivityPayloadWrite):
        raise ReplayActivityCorruptionError(
            "recorded activity store returned an invalid payload write"
        )
    actual.verify_integrity()
    if actual.payload == expected:
        return actual
    if (
        actual.payload.tenant_id != expected.tenant_id
        or actual.payload.security_classification
        is not expected.security_classification
    ):
        raise ReplayActivityTenantMismatchError(
            "recorded activity payload scope does not match"
        )
    if actual.payload.pinned_version != expected.pinned_version:
        raise ReplayActivityVersionError(
            "recorded activity payload version does not match"
        )
    raise ReplayActivityRecordingConflictError(
        "recorded activity payload identity or content does not match"
    )


def _validate_accepted_write(
    expected_pending: ReplayActivityRecord,
    actual: Any,
) -> RecordedActivityWrite:
    if not isinstance(actual, RecordedActivityWrite):
        raise ReplayActivityCorruptionError(
            "recorded activity store returned an invalid accepted write"
        )
    actual.verify_integrity()
    _validate_activity_descriptor(expected_pending.activity, actual.record.activity)
    if actual.record.outcome.started_at != expected_pending.outcome.started_at:
        raise ReplayActivityRecordingConflictError(
            "recorded activity start time does not match"
        )
    if (
        actual.record.outcome.status is ReplayActivityStatus.PENDING
        and actual.record != expected_pending
    ):
        raise ReplayActivityRecordingConflictError(
            "recorded pending activity does not match accepted input"
        )
    _validate_independent_terminal_reference(actual)
    return actual


def _validate_completed_write(
    expected_terminal: ReplayActivityRecord,
    actual: Any,
) -> RecordedActivityWrite:
    if not isinstance(actual, RecordedActivityWrite):
        raise ReplayActivityCorruptionError(
            "recorded activity store returned an invalid completion write"
        )
    actual.verify_integrity()
    _validate_activity_descriptor(expected_terminal.activity, actual.record.activity)
    if actual.record != expected_terminal:
        raise ReplayActivityRecordingConflictError(
            "recorded terminal activity does not match completion"
        )
    _validate_independent_terminal_reference(actual)
    return actual


def _validate_activity_descriptor(
    expected: ReplayActivityDescriptor,
    actual: ReplayActivityDescriptor,
) -> None:
    if (
        actual.tenant_id != expected.tenant_id
        or actual.security_classification is not expected.security_classification
    ):
        raise ReplayActivityTenantMismatchError(
            "recorded activity scope does not match"
        )
    if (
        actual.activity_id != expected.activity_id
        or actual.activity_kind is not expected.activity_kind
    ):
        raise ReplayActivityMismatchError("recorded activity identity does not match")
    if actual.pinned_version != expected.pinned_version:
        raise ReplayActivityVersionError("recorded activity version does not match")
    if (
        actual.input_ref != expected.input_ref
        or actual.input_checksum != expected.input_checksum
        or actual.idempotency_key != expected.idempotency_key
        or actual.attempt != expected.attempt
    ):
        raise ReplayActivityInputMismatchError(
            "recorded activity accepted input does not match"
        )
    if actual != expected:
        raise ReplayActivityRecordingConflictError(
            "recorded activity context or acceptance time does not match"
        )


def _validate_independent_terminal_reference(write: RecordedActivityWrite) -> None:
    outcome = write.record.outcome
    payload_ref = (
        outcome.output_ref
        if outcome.status is ReplayActivityStatus.SUCCEEDED
        else outcome.error_ref
    )
    if outcome.status is ReplayActivityStatus.PENDING:
        return
    if payload_ref is None:
        raise ReplayActivityCorruptionError(
            "recorded terminal activity is missing its payload reference"
        )
    if payload_ref.uri == write.recorded_ref.uri:
        raise ReplayActivityCorruptionError(
            "recorded terminal payload must be stored separately from its record"
        )


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _checksum(value: Any, field_name: str) -> str:
    normalized = _required_text(value, field_name).lower()
    if not normalized.startswith("sha256:") or len(normalized) != 71:
        raise ValueError(f"{field_name} must be sha256:<64 lowercase hex>")
    if any(character not in "0123456789abcdef" for character in normalized[7:]):
        raise ValueError(f"{field_name} must be sha256:<64 lowercase hex>")
    return normalized


def _datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return ensure_utc(value)


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _reject_unknown_fields(
    value: Mapping[str, Any],
    allowed: set[str],
    field_name: str,
) -> None:
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise ValueError(f"unknown {field_name} field(s): {', '.join(unknown)}")


__all__ = [
    "ActivityRecorder",
    "ActivityRecordingHandle",
    "REPLAY_ACTIVITY_PAYLOAD_CONTENT_TYPE",
    "REPLAY_ACTIVITY_RECORD_CONTENT_TYPE",
    "REPLAY_ACTIVITY_RECORD_SCHEMA",
    "RecordedActivityPayloadWrite",
    "RecordedActivityResolver",
    "RecordedActivityStorePort",
    "RecordedActivityWrite",
    "ReplayActivityCorruptionError",
    "ReplayActivityDescriptor",
    "ReplayActivityFailedError",
    "ReplayActivityHandlerVersion",
    "ReplayActivityInputMismatchError",
    "ReplayActivityIncompleteError",
    "ReplayActivityKind",
    "ReplayActivityMismatchError",
    "ReplayActivityMissingError",
    "ReplayActivityOutcome",
    "ReplayActivityPayload",
    "ReplayActivityPayloadRole",
    "ReplayActivityRecord",
    "ReplayActivityRecordingConflictError",
    "ReplayActivityRecordingError",
    "ReplayActivityRegistry",
    "ReplayActivityResolutionError",
    "ReplayActivityResolverPort",
    "ReplayActivityStatus",
    "ReplayActivityTenantMismatchError",
    "ReplayActivityVersionError",
    "ResolvedReplayActivity",
]
