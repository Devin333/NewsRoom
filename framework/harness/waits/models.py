from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.canonical import (
    canonical_checksum,
    exact_reference,
    required_text,
)
from framework.harness.graph.dsl import WaitKind


HARNESS_WAIT_RECORD_SCHEMA = "newsroom.harness.wait-record/v1"


class HarnessWaitCauseKind(StrEnum):
    SIGNAL = "signal"
    TIMER = "timer"
    TIMEOUT = "timeout"
    APPROVAL = "approval"
    CANCELLATION = "cancellation"


class HarnessSignalInboxEntryStatus(StrEnum):
    EARLY = "early"
    MATCHED = "matched"


@dataclass(frozen=True, slots=True)
class HarnessWaitScope:
    """Exact authority and correlation scope shared by every Wait record."""

    wait_id: str
    run_id: str
    node_instance_id: str
    tenant_scope_ref: str
    identity_scope_ref: str
    signal_schema_ref: str
    correlation_ref: str

    def __post_init__(self) -> None:
        for field_name in ("wait_id", "run_id", "node_instance_id"):
            object.__setattr__(
                self,
                field_name,
                required_text(getattr(self, field_name), f"wait_scope.{field_name}"),
            )
        for field_name in (
            "tenant_scope_ref",
            "identity_scope_ref",
            "correlation_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _checksum(getattr(self, field_name), f"wait_scope.{field_name}"),
            )
        object.__setattr__(
            self,
            "signal_schema_ref",
            exact_reference(
                self.signal_schema_ref,
                "wait_scope.signal_schema_ref",
            ),
        )

    @property
    def scope_ref(self) -> str:
        return canonical_checksum(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "wait_id": self.wait_id,
            "run_id": self.run_id,
            "node_instance_id": self.node_instance_id,
            "tenant_scope_ref": self.tenant_scope_ref,
            "identity_scope_ref": self.identity_scope_ref,
            "signal_schema_ref": self.signal_schema_ref,
            "correlation_ref": self.correlation_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessWaitScope:
        _exact_keys(
            value,
            {
                "wait_id",
                "run_id",
                "node_instance_id",
                "tenant_scope_ref",
                "identity_scope_ref",
                "signal_schema_ref",
                "correlation_ref",
            },
            "Wait scope",
        )
        return cls(
            wait_id=value["wait_id"],
            run_id=value["run_id"],
            node_instance_id=value["node_instance_id"],
            tenant_scope_ref=value["tenant_scope_ref"],
            identity_scope_ref=value["identity_scope_ref"],
            signal_schema_ref=value["signal_schema_ref"],
            correlation_ref=value["correlation_ref"],
        )


@dataclass(frozen=True, slots=True)
class HarnessWaitRegistrationRecord:
    scope: HarnessWaitScope
    kind: WaitKind | str
    registered_sequence: int
    deadline_ref: str | None = None
    record_schema: str = field(default=HARNESS_WAIT_RECORD_SCHEMA, init=False)

    def __post_init__(self) -> None:
        _scope(self.scope)
        kind = WaitKind(self.kind)
        _nonnegative_int(
            self.registered_sequence, "wait_registration.registered_sequence"
        )
        deadline_ref = _optional_checksum(
            self.deadline_ref,
            "wait_registration.deadline_ref",
        )
        if kind is WaitKind.TIMER and deadline_ref is None:
            raise HarnessValidationError(
                "timer Wait registration requires a durable deadline reference",
                code="timer_deadline_missing",
            )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "deadline_ref", deadline_ref)

    @property
    def registration_ref(self) -> str:
        return canonical_checksum(self.to_dict())

    def matches_scope(self, scope: HarnessWaitScope) -> bool:
        return self.scope == scope

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_schema": self.record_schema,
            "scope": self.scope.to_dict(),
            "kind": self.kind.value,
            "registered_sequence": self.registered_sequence,
            "deadline_ref": self.deadline_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessWaitRegistrationRecord:
        _record_keys(
            value,
            {"scope", "kind", "registered_sequence", "deadline_ref"},
            "Wait registration record",
        )
        return cls(
            scope=HarnessWaitScope.from_dict(_mapping(value["scope"], "scope")),
            kind=value["kind"],
            registered_sequence=value["registered_sequence"],
            deadline_ref=value["deadline_ref"],
        )


@dataclass(frozen=True, slots=True)
class HarnessWaitSignal:
    signal_id: str
    scope: HarnessWaitScope
    payload_ref: str
    received_sequence: int
    record_schema: str = field(default=HARNESS_WAIT_RECORD_SCHEMA, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "signal_id",
            required_text(self.signal_id, "wait_signal.signal_id"),
        )
        _scope(self.scope)
        object.__setattr__(
            self,
            "payload_ref",
            _checksum(self.payload_ref, "wait_signal.payload_ref"),
        )
        _nonnegative_int(self.received_sequence, "wait_signal.received_sequence")

    @property
    def identity_ref(self) -> str:
        return canonical_checksum(
            {"signal_id": self.signal_id, "scope": self.scope.to_dict()}
        )

    @property
    def signal_ref(self) -> str:
        return canonical_checksum(self.idempotency_projection())

    def idempotency_projection(self) -> dict[str, Any]:
        """Logical signal content; delivery retries may have another sequence."""

        return {
            "record_schema": self.record_schema,
            "signal_id": self.signal_id,
            "scope": self.scope.to_dict(),
            "payload_ref": self.payload_ref,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.idempotency_projection(),
            "received_sequence": self.received_sequence,
            "signal_ref": self.signal_ref,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessWaitSignal:
        _record_keys(
            value,
            {
                "signal_id",
                "scope",
                "payload_ref",
                "received_sequence",
                "signal_ref",
            },
            "Wait signal",
        )
        signal = cls(
            signal_id=value["signal_id"],
            scope=HarnessWaitScope.from_dict(_mapping(value["scope"], "scope")),
            payload_ref=value["payload_ref"],
            received_sequence=value["received_sequence"],
        )
        if value["signal_ref"] != signal.signal_ref:
            raise HarnessValidationError(
                "Wait signal reference does not match canonical content",
                code="wait_signal_checksum_mismatch",
            )
        return signal


@dataclass(frozen=True, slots=True)
class HarnessWaitSignalMatch:
    scope: HarnessWaitScope
    registration_ref: str
    signal_ref: str
    matched_sequence: int
    record_schema: str = field(default=HARNESS_WAIT_RECORD_SCHEMA, init=False)

    def __post_init__(self) -> None:
        _scope(self.scope)
        object.__setattr__(
            self,
            "registration_ref",
            _checksum(self.registration_ref, "signal_match.registration_ref"),
        )
        object.__setattr__(
            self,
            "signal_ref",
            _checksum(self.signal_ref, "signal_match.signal_ref"),
        )
        _nonnegative_int(self.matched_sequence, "signal_match.matched_sequence")

    @property
    def match_ref(self) -> str:
        return canonical_checksum(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_schema": self.record_schema,
            "scope": self.scope.to_dict(),
            "registration_ref": self.registration_ref,
            "signal_ref": self.signal_ref,
            "matched_sequence": self.matched_sequence,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessWaitSignalMatch:
        _record_keys(
            value,
            {"scope", "registration_ref", "signal_ref", "matched_sequence"},
            "Wait signal match",
        )
        return cls(
            scope=HarnessWaitScope.from_dict(_mapping(value["scope"], "scope")),
            registration_ref=value["registration_ref"],
            signal_ref=value["signal_ref"],
            matched_sequence=value["matched_sequence"],
        )


@dataclass(frozen=True, slots=True)
class HarnessSignalInboxEntry:
    signal: HarnessWaitSignal
    status: HarnessSignalInboxEntryStatus | str = HarnessSignalInboxEntryStatus.EARLY
    match: HarnessWaitSignalMatch | None = None
    record_schema: str = field(default=HARNESS_WAIT_RECORD_SCHEMA, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.signal, HarnessWaitSignal):
            raise TypeError("signal must be HarnessWaitSignal")
        status = HarnessSignalInboxEntryStatus(self.status)
        if self.match is not None:
            if not isinstance(self.match, HarnessWaitSignalMatch):
                raise TypeError("match must be HarnessWaitSignalMatch")
            if self.match.signal_ref != self.signal.signal_ref:
                raise HarnessValidationError(
                    "signal inbox match references another signal",
                    code="wait_signal_match_mismatch",
                )
            if self.match.scope != self.signal.scope:
                raise HarnessValidationError(
                    "signal inbox match belongs to another scope",
                    code="wait_signal_scope_mismatch",
                )
        if status is HarnessSignalInboxEntryStatus.EARLY and self.match is not None:
            raise HarnessValidationError(
                "early signal inbox entry cannot carry a match",
                code="invalid_signal_inbox_entry",
            )
        if status is HarnessSignalInboxEntryStatus.MATCHED and self.match is None:
            raise HarnessValidationError(
                "matched signal inbox entry requires durable match evidence",
                code="invalid_signal_inbox_entry",
            )
        object.__setattr__(self, "status", status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_schema": self.record_schema,
            "signal": self.signal.to_dict(),
            "status": self.status.value,
            "match": None if self.match is None else self.match.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessSignalInboxEntry:
        _record_keys(
            value,
            {"signal", "status", "match"},
            "signal inbox entry",
        )
        match = value["match"]
        return cls(
            signal=HarnessWaitSignal.from_dict(_mapping(value["signal"], "signal")),
            status=value["status"],
            match=(
                None
                if match is None
                else HarnessWaitSignalMatch.from_dict(_mapping(match, "match"))
            ),
        )


@dataclass(frozen=True, slots=True)
class HarnessEarlySignalRetentionPolicy:
    max_signals: int = 1024
    max_signals_per_scope: int = 32
    sequence_window: int = 100_000

    def __post_init__(self) -> None:
        for field_name in (
            "max_signals",
            "max_signals_per_scope",
            "sequence_window",
        ):
            _positive_int(getattr(self, field_name), f"signal_retention.{field_name}")
        if self.max_signals_per_scope > self.max_signals:
            raise HarnessValidationError(
                "per-scope signal retention cannot exceed the total bound",
                code="invalid_signal_retention_policy",
            )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_signals": self.max_signals,
            "max_signals_per_scope": self.max_signals_per_scope,
            "sequence_window": self.sequence_window,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> HarnessEarlySignalRetentionPolicy:
        _exact_keys(
            value,
            {"max_signals", "max_signals_per_scope", "sequence_window"},
            "early signal retention policy",
        )
        return cls(
            max_signals=value["max_signals"],
            max_signals_per_scope=value["max_signals_per_scope"],
            sequence_window=value["sequence_window"],
        )


@dataclass(frozen=True, slots=True)
class HarnessWaitTimerWakeRecord:
    scope: HarnessWaitScope
    deadline_ref: str
    timer_event_ref: str
    recorded_sequence: int
    record_schema: str = field(default=HARNESS_WAIT_RECORD_SCHEMA, init=False)

    def __post_init__(self) -> None:
        _scope(self.scope)
        object.__setattr__(
            self,
            "deadline_ref",
            _checksum(self.deadline_ref, "timer_wake.deadline_ref"),
        )
        object.__setattr__(
            self,
            "timer_event_ref",
            _checksum(self.timer_event_ref, "timer_wake.timer_event_ref"),
        )
        _nonnegative_int(self.recorded_sequence, "timer_wake.recorded_sequence")

    @property
    def wake_ref(self) -> str:
        return canonical_checksum(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _cause_dict(
            self.record_schema,
            self.scope,
            {
                "deadline_ref": self.deadline_ref,
                "timer_event_ref": self.timer_event_ref,
                "recorded_sequence": self.recorded_sequence,
            },
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessWaitTimerWakeRecord:
        _record_keys(
            value,
            {"scope", "deadline_ref", "timer_event_ref", "recorded_sequence"},
            "Wait timer wake",
        )
        return cls(
            scope=HarnessWaitScope.from_dict(_mapping(value["scope"], "scope")),
            deadline_ref=value["deadline_ref"],
            timer_event_ref=value["timer_event_ref"],
            recorded_sequence=value["recorded_sequence"],
        )


@dataclass(frozen=True, slots=True)
class HarnessWaitApprovalEvidenceRecord:
    scope: HarnessWaitScope
    approval_event_ref: str
    actor_identity_scope_ref: str
    approved: bool
    recorded_sequence: int
    # These fields were added after the v1 wait record contract.  They are
    # optional only for replaying historical v1 records; new application
    # service submissions must provide the complete Graph binding.
    approval_id: str | None = None
    graph_id: str | None = None
    graph_version: str | None = None
    graph_ref: str | None = None
    graph_checksum: str | None = None
    record_schema: str = field(default=HARNESS_WAIT_RECORD_SCHEMA, init=False)

    def __post_init__(self) -> None:
        _scope(self.scope)
        if self.approval_id is not None:
            object.__setattr__(
                self,
                "approval_id",
                required_text(self.approval_id, "approval_evidence.approval_id"),
            )
        graph_values = (
            self.graph_id,
            self.graph_version,
            self.graph_ref,
            self.graph_checksum,
        )
        if any(value is not None for value in graph_values):
            if any(value is None for value in graph_values):
                raise HarnessValidationError(
                    "approval evidence must bind all Graph identity fields",
                    code="invalid_wait_approval_graph_binding",
                )
            object.__setattr__(
                self,
                "graph_id",
                required_text(self.graph_id, "approval_evidence.graph_id"),
            )
            object.__setattr__(
                self,
                "graph_version",
                required_text(self.graph_version, "approval_evidence.graph_version"),
            )
            object.__setattr__(
                self,
                "graph_ref",
                exact_reference(self.graph_ref, "approval_evidence.graph_ref"),
            )
            object.__setattr__(
                self,
                "graph_checksum",
                _checksum(self.graph_checksum, "approval_evidence.graph_checksum"),
            )
        object.__setattr__(
            self,
            "approval_event_ref",
            _checksum(self.approval_event_ref, "approval_evidence.approval_event_ref"),
        )
        object.__setattr__(
            self,
            "actor_identity_scope_ref",
            _checksum(
                self.actor_identity_scope_ref,
                "approval_evidence.actor_identity_scope_ref",
            ),
        )
        if not isinstance(self.approved, bool):
            raise HarnessValidationError(
                "approval evidence approved must be boolean",
                code="invalid_wait_approval_evidence",
            )
        _nonnegative_int(
            self.recorded_sequence,
            "approval_evidence.recorded_sequence",
        )

    @property
    def approval_ref(self) -> str:
        return canonical_checksum(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        values = {
            "approval_event_ref": self.approval_event_ref,
            "actor_identity_scope_ref": self.actor_identity_scope_ref,
            "approved": self.approved,
            "recorded_sequence": self.recorded_sequence,
        }
        if self.approval_id is not None:
            values.update(
                {
                    "approval_id": self.approval_id,
                    "graph_id": self.graph_id,
                    "graph_version": self.graph_version,
                    "graph_ref": self.graph_ref,
                    "graph_checksum": self.graph_checksum,
                }
            )
        return _cause_dict(
            self.record_schema,
            self.scope,
            values,
        )

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> HarnessWaitApprovalEvidenceRecord:
        base_fields = {
            "scope",
            "approval_event_ref",
            "actor_identity_scope_ref",
            "approved",
            "recorded_sequence",
        }
        graph_fields = {
            "approval_id",
            "graph_id",
            "graph_version",
            "graph_ref",
            "graph_checksum",
        }
        expected_fields = base_fields | (graph_fields if "approval_id" in value else set())
        _record_keys(value, expected_fields, "Wait approval evidence")
        return cls(
            scope=HarnessWaitScope.from_dict(_mapping(value["scope"], "scope")),
            approval_event_ref=value["approval_event_ref"],
            actor_identity_scope_ref=value["actor_identity_scope_ref"],
            approved=value["approved"],
            recorded_sequence=value["recorded_sequence"],
            approval_id=value.get("approval_id"),
            graph_id=value.get("graph_id"),
            graph_version=value.get("graph_version"),
            graph_ref=value.get("graph_ref"),
            graph_checksum=value.get("graph_checksum"),
        )


def approval_event_ref_for(
    *,
    approval_id: str,
    scope: HarnessWaitScope,
    actor_identity_scope_ref: str,
    approved: bool,
    graph_id: str,
    graph_version: str,
    graph_ref: str,
    graph_checksum: str,
) -> str:
    """Return the canonical, Graph-bound approval event reference."""

    return canonical_checksum(
        {
            "approval_id": required_text(approval_id, "approval_id"),
            "scope": scope.to_dict(),
            "actor_identity_scope_ref": _checksum(
                actor_identity_scope_ref,
                "actor_identity_scope_ref",
            ),
            "approved": approved,
            "graph_id": required_text(graph_id, "graph_id"),
            "graph_version": required_text(graph_version, "graph_version"),
            "graph_ref": exact_reference(graph_ref, "graph_ref"),
            "graph_checksum": _checksum(graph_checksum, "graph_checksum"),
        }
    )


@dataclass(frozen=True, slots=True)
class HarnessWaitResumeRecord:
    scope: HarnessWaitScope
    cause_kind: HarnessWaitCauseKind | str
    cause_ref: str
    resumed_sequence: int
    record_schema: str = field(default=HARNESS_WAIT_RECORD_SCHEMA, init=False)

    def __post_init__(self) -> None:
        _scope(self.scope)
        object.__setattr__(self, "cause_kind", HarnessWaitCauseKind(self.cause_kind))
        object.__setattr__(
            self,
            "cause_ref",
            _checksum(self.cause_ref, "wait_resume.cause_ref"),
        )
        _nonnegative_int(self.resumed_sequence, "wait_resume.resumed_sequence")

    @property
    def resume_ref(self) -> str:
        return canonical_checksum(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _cause_dict(
            self.record_schema,
            self.scope,
            {
                "cause_kind": self.cause_kind.value,
                "cause_ref": self.cause_ref,
                "resumed_sequence": self.resumed_sequence,
            },
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessWaitResumeRecord:
        _record_keys(
            value,
            {"scope", "cause_kind", "cause_ref", "resumed_sequence"},
            "Wait resume",
        )
        return cls(
            scope=HarnessWaitScope.from_dict(_mapping(value["scope"], "scope")),
            cause_kind=value["cause_kind"],
            cause_ref=value["cause_ref"],
            resumed_sequence=value["resumed_sequence"],
        )


@dataclass(frozen=True, slots=True)
class HarnessWaitTimeoutRecord:
    scope: HarnessWaitScope
    deadline_ref: str
    timeout_event_ref: str
    timed_out_sequence: int
    record_schema: str = field(default=HARNESS_WAIT_RECORD_SCHEMA, init=False)

    def __post_init__(self) -> None:
        _scope(self.scope)
        object.__setattr__(
            self,
            "deadline_ref",
            _checksum(self.deadline_ref, "wait_timeout.deadline_ref"),
        )
        object.__setattr__(
            self,
            "timeout_event_ref",
            _checksum(self.timeout_event_ref, "wait_timeout.timeout_event_ref"),
        )
        _nonnegative_int(self.timed_out_sequence, "wait_timeout.timed_out_sequence")

    @property
    def timeout_ref(self) -> str:
        return canonical_checksum(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _cause_dict(
            self.record_schema,
            self.scope,
            {
                "deadline_ref": self.deadline_ref,
                "timeout_event_ref": self.timeout_event_ref,
                "timed_out_sequence": self.timed_out_sequence,
            },
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessWaitTimeoutRecord:
        _record_keys(
            value,
            {"scope", "deadline_ref", "timeout_event_ref", "timed_out_sequence"},
            "Wait timeout",
        )
        return cls(
            scope=HarnessWaitScope.from_dict(_mapping(value["scope"], "scope")),
            deadline_ref=value["deadline_ref"],
            timeout_event_ref=value["timeout_event_ref"],
            timed_out_sequence=value["timed_out_sequence"],
        )


@dataclass(frozen=True, slots=True)
class HarnessWaitCancellationRecord:
    scope: HarnessWaitScope
    cancellation_event_ref: str
    actor_identity_scope_ref: str
    reason_code: str
    cancelled_sequence: int
    record_schema: str = field(default=HARNESS_WAIT_RECORD_SCHEMA, init=False)

    def __post_init__(self) -> None:
        _scope(self.scope)
        object.__setattr__(
            self,
            "cancellation_event_ref",
            _checksum(
                self.cancellation_event_ref,
                "wait_cancellation.cancellation_event_ref",
            ),
        )
        object.__setattr__(
            self,
            "actor_identity_scope_ref",
            _checksum(
                self.actor_identity_scope_ref,
                "wait_cancellation.actor_identity_scope_ref",
            ),
        )
        object.__setattr__(
            self,
            "reason_code",
            required_text(self.reason_code, "wait_cancellation.reason_code"),
        )
        _nonnegative_int(
            self.cancelled_sequence,
            "wait_cancellation.cancelled_sequence",
        )

    @property
    def cancellation_ref(self) -> str:
        return canonical_checksum(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _cause_dict(
            self.record_schema,
            self.scope,
            {
                "cancellation_event_ref": self.cancellation_event_ref,
                "actor_identity_scope_ref": self.actor_identity_scope_ref,
                "reason_code": self.reason_code,
                "cancelled_sequence": self.cancelled_sequence,
            },
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessWaitCancellationRecord:
        _record_keys(
            value,
            {
                "scope",
                "cancellation_event_ref",
                "actor_identity_scope_ref",
                "reason_code",
                "cancelled_sequence",
            },
            "Wait cancellation",
        )
        return cls(
            scope=HarnessWaitScope.from_dict(_mapping(value["scope"], "scope")),
            cancellation_event_ref=value["cancellation_event_ref"],
            actor_identity_scope_ref=value["actor_identity_scope_ref"],
            reason_code=value["reason_code"],
            cancelled_sequence=value["cancelled_sequence"],
        )


HarnessTimerWake = HarnessWaitTimerWakeRecord
HarnessApprovalEvidence = HarnessWaitApprovalEvidenceRecord
HarnessWaitResume = HarnessWaitResumeRecord
HarnessWaitTimeout = HarnessWaitTimeoutRecord
HarnessWaitCancellation = HarnessWaitCancellationRecord


def validate_signal_authorization(
    signal: HarnessWaitSignal,
    authorized_scope: HarnessWaitScope,
) -> None:
    if not isinstance(signal, HarnessWaitSignal):
        raise TypeError("signal must be HarnessWaitSignal")
    _scope(authorized_scope)
    _validate_scope_match(
        expected=authorized_scope,
        actual=signal.scope,
        prefix="wait_signal_authorization",
    )


def validate_signal_for_registration(
    registration: HarnessWaitRegistrationRecord,
    signal: HarnessWaitSignal,
) -> None:
    if not isinstance(registration, HarnessWaitRegistrationRecord):
        raise TypeError("registration must be HarnessWaitRegistrationRecord")
    if not isinstance(signal, HarnessWaitSignal):
        raise TypeError("signal must be HarnessWaitSignal")
    if registration.kind is not WaitKind.SIGNAL:
        raise HarnessValidationError(
            "only signal Wait registrations may consume signal inbox entries",
            code="wait_signal_kind_mismatch",
        )
    _validate_scope_match(
        expected=registration.scope,
        actual=signal.scope,
        prefix="wait_signal",
    )


def _validate_scope_match(
    *,
    expected: HarnessWaitScope,
    actual: HarnessWaitScope,
    prefix: str,
) -> None:
    fields_and_codes = (
        ("wait_id", "wait_mismatch"),
        ("run_id", "run_scope_mismatch"),
        ("node_instance_id", "node_scope_mismatch"),
        ("tenant_scope_ref", "tenant_scope_mismatch"),
        ("identity_scope_ref", "identity_scope_mismatch"),
        ("signal_schema_ref", "schema_mismatch"),
        ("correlation_ref", "correlation_mismatch"),
    )
    for field_name, suffix in fields_and_codes:
        if getattr(expected, field_name) != getattr(actual, field_name):
            raise HarnessValidationError(
                f"Wait signal {field_name} does not match the authorized scope",
                code=f"{prefix}_{suffix}",
                details={"field": field_name},
            )


def _cause_dict(
    record_schema: str,
    scope: HarnessWaitScope,
    values: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "record_schema": record_schema,
        "scope": scope.to_dict(),
        **dict(values),
    }


def _scope(value: Any) -> HarnessWaitScope:
    if not isinstance(value, HarnessWaitScope):
        raise TypeError("scope must be HarnessWaitScope")
    return value


def _checksum(value: Any, field_name: str) -> str:
    text = required_text(value, field_name)
    if not text.startswith("sha256:"):
        raise HarnessValidationError(
            f"{field_name} must be a sha256 reference",
            code="invalid_wait_reference",
            details={"field": field_name},
        )
    digest = text.removeprefix("sha256:")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise HarnessValidationError(
            f"{field_name} must be a sha256 reference",
            code="invalid_wait_reference",
            details={"field": field_name},
        )
    return text


def _optional_checksum(value: Any, field_name: str) -> str | None:
    return None if value is None else _checksum(value, field_name)


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HarnessValidationError(
            f"{field_name} must be a non-negative integer",
            code="invalid_wait_sequence",
            details={"field": field_name},
        )
    return value


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HarnessValidationError(
            f"{field_name} must be a positive integer",
            code="invalid_signal_retention_policy",
            details={"field": field_name},
        )
    return value


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            f"{field_name} must be an object",
            code="invalid_wait_record",
        )
    return value


def _record_keys(
    value: Mapping[str, Any],
    fields: set[str],
    field_name: str,
) -> None:
    _exact_keys(value, fields | {"record_schema"}, field_name)
    if value["record_schema"] != HARNESS_WAIT_RECORD_SCHEMA:
        raise HarnessValidationError(
            "unsupported Harness Wait record schema",
            code="unsupported_wait_record_schema",
            details={"record_schema": str(value["record_schema"])},
        )


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    field_name: str,
) -> None:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(
            f"{field_name} must be an object",
            code="invalid_wait_record",
        )
    actual = set(value)
    if actual != expected:
        raise HarnessValidationError(
            f"{field_name} fields do not match the versioned contract",
            code="invalid_wait_record_fields",
            details={
                "missing": sorted(expected - actual),
                "unknown": sorted(actual - expected),
            },
        )


__all__ = [
    "HARNESS_WAIT_RECORD_SCHEMA",
    "HarnessApprovalEvidence",
    "HarnessEarlySignalRetentionPolicy",
    "HarnessSignalInboxEntry",
    "HarnessSignalInboxEntryStatus",
    "HarnessTimerWake",
    "HarnessWaitApprovalEvidenceRecord",
    "approval_event_ref_for",
    "HarnessWaitCancellation",
    "HarnessWaitCancellationRecord",
    "HarnessWaitCauseKind",
    "HarnessWaitRegistrationRecord",
    "HarnessWaitResume",
    "HarnessWaitResumeRecord",
    "HarnessWaitScope",
    "HarnessWaitSignal",
    "HarnessWaitSignalMatch",
    "HarnessWaitTimeout",
    "HarnessWaitTimeoutRecord",
    "HarnessWaitTimerWakeRecord",
    "validate_signal_authorization",
    "validate_signal_for_registration",
]
