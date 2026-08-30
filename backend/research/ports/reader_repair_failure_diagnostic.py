from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from framework.events.canonical import checksum_for
from framework.harness.control_plane.terminal_failure import (
    HARNESS_GRAPH_TERMINAL_FAILURE_RECORD_SCHEMA,
    HarnessGraphTerminalFailureRecord,
)
from framework.shared.time import format_datetime

from backend.research.domain.reader_repair import (
    READER_REPAIR_NAMESPACE,
    ReaderRepairCase,
    stable_research_id,
)
from backend.research.ports.repair_memory import reader_repair_case_memory_ref


READER_REPAIR_FAILURE_DIAGNOSTIC_EFFECT_KIND = "memory_write_failure_diagnostic"
READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_ID = (
    "research.reader_repair.memory.failure_diagnostic.commit"
)
READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_VERSION = "1"
READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF = (
    f"{READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_ID}"
    f"@{READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_VERSION}"
)
READER_REPAIR_FAILURE_DIAGNOSTIC_SCHEMA_VERSION = (
    "newsroom.research-reader-repair-failure-diagnostic/v1"
)
READER_REPAIR_FAILURE_DIAGNOSTIC_TERMINAL_ACTION = (
    "record_failure_diagnostic"
)

_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_KEYS = frozenset(
    {
        "active_skill_package",
        "artifact_ref",
        "production_skill_version",
        "promote_skill",
        "public_ref",
        "publish",
        "publish_artifact",
        "skill_candidate",
        "strategy_candidate_bundle",
    }
)
_INPUT_BINDING_FIELDS = frozenset(
    {
        "terminal_failure_record",
        "reader_issue",
        "reader_repair_patch_candidate",
        "reader_repair_application",
        "reader_repair_application_observation",
        "reader_repair_application_verification",
    }
)


@dataclass(frozen=True, slots=True)
class ReaderRepairFailureDiagnosticCandidate:
    """Failure-only case candidate derived after durable Graph termination."""

    candidate_id: str
    run_id: str
    terminal_failure: HarnessGraphTerminalFailureRecord
    repair_case: ReaderRepairCase
    repair_candidate_ref: str
    application_ref: str
    observation_ref: str
    verification_ref: str
    failed_gate_evidence_refs: tuple[str, ...]
    schema_version: str = READER_REPAIR_FAILURE_DIAGNOSTIC_SCHEMA_VERSION
    checksum: str | None = field(default=None, compare=True)

    def __post_init__(self) -> None:
        candidate_id = _require_text(self.candidate_id, "candidate_id")
        run_id = _require_text(self.run_id, "run_id")
        if not isinstance(self.terminal_failure, HarnessGraphTerminalFailureRecord):
            raise TypeError(
                "terminal_failure must be HarnessGraphTerminalFailureRecord"
            )
        if not isinstance(self.repair_case, ReaderRepairCase):
            raise TypeError("repair_case must be ReaderRepairCase")
        terminal_failure = self.terminal_failure
        repair_case = self.repair_case.model_copy(deep=True)
        terminal_failure_shape = (
            terminal_failure.terminal_decision_type.value,
            terminal_failure.terminal_reason_code,
        )
        if (
            terminal_failure.run_id != run_id
            or terminal_failure_shape
            not in {
                ("complete_run", "graph_terminal_failure"),
                ("halt_run", "verification_failed_replans_exhausted"),
            }
            or terminal_failure.schema_version
            != HARNESS_GRAPH_TERMINAL_FAILURE_RECORD_SCHEMA
        ):
            raise ValueError(
                "reader repair diagnostic terminal failure identity is invalid"
            )
        if repair_case.issue.run_id != run_id:
            raise ValueError("reader repair diagnostic issue belongs to another run")
        if (
            repair_case.successful
            or repair_case.payload_after_ref is not None
            or not isinstance(repair_case.failure_reason, str)
            or not repair_case.failure_reason.strip()
        ):
            raise ValueError(
                "reader repair diagnostic case must be an explicit failed outcome"
            )
        if not any(
            isinstance(item, Mapping) and item.get("passed") is False
            for item in repair_case.verification_results
        ):
            raise ValueError(
                "reader repair diagnostic case requires failed verification evidence"
            )

        repair_candidate_ref = _require_checksum(
            self.repair_candidate_ref,
            "repair_candidate_ref",
        )
        application_ref = _require_checksum(self.application_ref, "application_ref")
        observation_ref = _require_checksum(self.observation_ref, "observation_ref")
        verification_ref = _require_checksum(
            self.verification_ref,
            "verification_ref",
        )
        gate_refs = tuple(
            sorted(
                _require_checksum(item, "failed_gate_evidence_refs")
                for item in self.failed_gate_evidence_refs
            )
        )
        if not gate_refs or len(gate_refs) != len(set(gate_refs)):
            raise ValueError(
                "reader repair diagnostic failed gate evidence must be unique and non-empty"
            )
        if not set(gate_refs).issubset(
            terminal_failure.gate_evidence_refs
        ) or not set(gate_refs).issubset(
            terminal_failure.decision_evidence_refs
        ):
            raise ValueError(
                "reader repair diagnostic gate evidence is outside terminal failure"
            )

        record_ref = terminal_failure.record_checksum
        if record_ref is None:  # pragma: no cover - model invariant
            raise AssertionError("terminal failure record checksum is missing")
        expected_bindings = {
            "terminal_failure_record": record_ref,
            "reader_issue": checksum_for(repair_case.issue.to_dict()),
            "reader_repair_patch_candidate": repair_candidate_ref,
            "reader_repair_application": application_ref,
            "reader_repair_application_observation": observation_ref,
            "reader_repair_application_verification": verification_ref,
        }
        raw_bindings = repair_case.metadata.get("input_bindings")
        if (
            not isinstance(raw_bindings, Mapping)
            or set(raw_bindings) != _INPUT_BINDING_FIELDS
            or dict(raw_bindings) != expected_bindings
            or repair_case.metadata.get("active_skill_mutation") is not False
            or repair_case.metadata.get("memory_record_kind")
            != "failed_repair_diagnostic"
            or repair_case.metadata.get("terminal_failure_record_ref") != record_ref
        ):
            raise ValueError(
                "reader repair diagnostic case input bindings are invalid"
            )
        forbidden = _nested_keys(
            (
                repair_case.to_dict(),
                terminal_failure.to_dict(),
            )
        ).intersection(_FORBIDDEN_KEYS)
        if forbidden:
            raise ValueError(
                "reader repair diagnostic contains forbidden publication or promotion fields: "
                f"{sorted(forbidden)}"
            )
        expected_candidate_id = stable_research_id(
            "repair_failure_diagnostic",
            run_id,
            record_ref,
            repair_case.repair_case_id,
        )
        if candidate_id != expected_candidate_id:
            raise ValueError("reader repair diagnostic candidate id is invalid")
        if self.schema_version != READER_REPAIR_FAILURE_DIAGNOSTIC_SCHEMA_VERSION:
            raise ValueError("reader repair failure diagnostic schema is unsupported")

        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "repair_case", repair_case)
        object.__setattr__(self, "repair_candidate_ref", repair_candidate_ref)
        object.__setattr__(self, "application_ref", application_ref)
        object.__setattr__(self, "observation_ref", observation_ref)
        object.__setattr__(self, "verification_ref", verification_ref)
        object.__setattr__(self, "failed_gate_evidence_refs", gate_refs)
        expected = checksum_for(self._checksum_payload())
        if self.checksum is not None and self.checksum != expected:
            raise ValueError(
                "reader repair failure diagnostic candidate checksum does not match"
            )
        object.__setattr__(self, "checksum", expected)

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> ReaderRepairFailureDiagnosticCandidate:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "candidate_id",
                "run_id",
                "terminal_failure",
                "repair_case",
                "repair_candidate_ref",
                "application_ref",
                "observation_ref",
                "verification_ref",
                "failed_gate_evidence_refs",
                "checksum",
            },
            "reader repair failure diagnostic candidate",
        )
        return cls(
            schema_version=payload["schema_version"],
            candidate_id=payload["candidate_id"],
            run_id=payload["run_id"],
            terminal_failure=HarnessGraphTerminalFailureRecord.from_dict(
                _mapping(payload["terminal_failure"], "terminal_failure")
            ),
            repair_case=ReaderRepairCase.model_validate(
                _deep_mutable(payload["repair_case"])
            ),
            repair_candidate_ref=payload["repair_candidate_ref"],
            application_ref=payload["application_ref"],
            observation_ref=payload["observation_ref"],
            verification_ref=payload["verification_ref"],
            failed_gate_evidence_refs=tuple(payload["failed_gate_evidence_refs"]),
            checksum=payload["checksum"],
        )

    def _checksum_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "run_id": self.run_id,
            "terminal_failure": self.terminal_failure.to_dict(),
            "repair_case": self.repair_case.to_dict(),
            "repair_candidate_ref": self.repair_candidate_ref,
            "application_ref": self.application_ref,
            "observation_ref": self.observation_ref,
            "verification_ref": self.verification_ref,
            "failed_gate_evidence_refs": list(self.failed_gate_evidence_refs),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._checksum_payload(), "checksum": self.checksum}


@dataclass(frozen=True, slots=True)
class ReaderRepairFailureDiagnosticCommitRequest:
    request_id: str
    run_id: str
    terminal_effect_id: str
    candidate: ReaderRepairFailureDiagnosticCandidate
    candidate_checksum: str
    authorization_ref: str
    identity_scope_ref: str
    subject_scope_ref: str
    atomic_group: str
    idempotency_key: str
    schema_version: str = READER_REPAIR_FAILURE_DIAGNOSTIC_SCHEMA_VERSION
    checksum: str | None = field(default=None, compare=True)

    def __post_init__(self) -> None:
        for field_name in (
            "request_id",
            "run_id",
            "terminal_effect_id",
            "atomic_group",
            "idempotency_key",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_text(getattr(self, field_name), field_name),
            )
        for field_name in (
            "candidate_checksum",
            "authorization_ref",
            "identity_scope_ref",
            "subject_scope_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_checksum(getattr(self, field_name), field_name),
            )
        if not isinstance(self.candidate, ReaderRepairFailureDiagnosticCandidate):
            raise TypeError(
                "candidate must be ReaderRepairFailureDiagnosticCandidate"
            )
        if (
            self.candidate.run_id != self.run_id
            or self.candidate.checksum != self.candidate_checksum
        ):
            raise ValueError(
                "reader repair failure diagnostic request candidate does not match"
            )
        if self.schema_version != READER_REPAIR_FAILURE_DIAGNOSTIC_SCHEMA_VERSION:
            raise ValueError("reader repair failure diagnostic schema is unsupported")
        expected = checksum_for(self._checksum_payload())
        if self.checksum is not None and self.checksum != expected:
            raise ValueError(
                "reader repair failure diagnostic request checksum does not match"
            )
        object.__setattr__(self, "checksum", expected)

    def _checksum_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "terminal_effect_id": self.terminal_effect_id,
            "candidate": self.candidate.to_dict(),
            "candidate_checksum": self.candidate_checksum,
            "authorization_ref": self.authorization_ref,
            "identity_scope_ref": self.identity_scope_ref,
            "subject_scope_ref": self.subject_scope_ref,
            "atomic_group": self.atomic_group,
            "idempotency_key": self.idempotency_key,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._checksum_payload(), "checksum": self.checksum}


@dataclass(frozen=True, slots=True)
class ReaderRepairFailureDiagnosticCommitReceipt:
    receipt_id: str
    request_ref: str
    run_id: str
    terminal_effect_id: str
    authorization_ref: str
    idempotency_key: str
    namespace: str
    diagnostic_case_ref: str
    diagnostic_case_version: int
    terminal_failure_record_ref: str
    committed_at: datetime
    schema_version: str = READER_REPAIR_FAILURE_DIAGNOSTIC_SCHEMA_VERSION
    checksum: str | None = field(default=None, compare=True)

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "run_id",
            "terminal_effect_id",
            "idempotency_key",
            "diagnostic_case_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_text(getattr(self, field_name), field_name),
            )
        for field_name in (
            "request_ref",
            "authorization_ref",
            "terminal_failure_record_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_checksum(getattr(self, field_name), field_name),
            )
        if self.namespace != READER_REPAIR_NAMESPACE:
            raise ValueError("reader repair diagnostic receipt namespace is invalid")
        version = _positive_int(
            self.diagnostic_case_version,
            "diagnostic_case_version",
        )
        if not isinstance(self.committed_at, datetime):
            raise TypeError("committed_at must be datetime")
        if self.committed_at.tzinfo is None or self.committed_at.utcoffset() is None:
            raise ValueError("committed_at must be timezone-aware")
        committed_at = self.committed_at.astimezone(UTC)
        if self.schema_version != READER_REPAIR_FAILURE_DIAGNOSTIC_SCHEMA_VERSION:
            raise ValueError("reader repair failure diagnostic schema is unsupported")
        object.__setattr__(self, "diagnostic_case_version", version)
        object.__setattr__(self, "committed_at", committed_at)
        expected = checksum_for(self._checksum_payload())
        if self.checksum is not None and self.checksum != expected:
            raise ValueError(
                "reader repair failure diagnostic receipt checksum does not match"
            )
        object.__setattr__(self, "checksum", expected)

    @property
    def public_refs(self) -> tuple[str, ...]:
        return ()

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> ReaderRepairFailureDiagnosticCommitReceipt:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "receipt_id",
                "request_ref",
                "run_id",
                "terminal_effect_id",
                "authorization_ref",
                "idempotency_key",
                "namespace",
                "diagnostic_case_ref",
                "diagnostic_case_version",
                "terminal_failure_record_ref",
                "committed_at",
                "checksum",
            },
            "reader repair failure diagnostic receipt",
        )
        committed_at = payload["committed_at"]
        if not isinstance(committed_at, str):
            raise TypeError("diagnostic receipt committed_at must be a string")
        return cls(
            schema_version=payload["schema_version"],
            receipt_id=payload["receipt_id"],
            request_ref=payload["request_ref"],
            run_id=payload["run_id"],
            terminal_effect_id=payload["terminal_effect_id"],
            authorization_ref=payload["authorization_ref"],
            idempotency_key=payload["idempotency_key"],
            namespace=payload["namespace"],
            diagnostic_case_ref=payload["diagnostic_case_ref"],
            diagnostic_case_version=payload["diagnostic_case_version"],
            terminal_failure_record_ref=payload["terminal_failure_record_ref"],
            committed_at=datetime.fromisoformat(committed_at.replace("Z", "+00:00")),
            checksum=payload["checksum"],
        )

    def _checksum_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "request_ref": self.request_ref,
            "run_id": self.run_id,
            "terminal_effect_id": self.terminal_effect_id,
            "authorization_ref": self.authorization_ref,
            "idempotency_key": self.idempotency_key,
            "namespace": self.namespace,
            "diagnostic_case_ref": self.diagnostic_case_ref,
            "diagnostic_case_version": self.diagnostic_case_version,
            "terminal_failure_record_ref": self.terminal_failure_record_ref,
            "committed_at": format_datetime(self.committed_at),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._checksum_payload(), "checksum": self.checksum}


@runtime_checkable
class ReaderRepairFailureDiagnosticCommitPort(Protocol):
    def commit_failure_diagnostic(
        self,
        request: ReaderRepairFailureDiagnosticCommitRequest,
    ) -> ReaderRepairFailureDiagnosticCommitReceipt:
        ...


def diagnostic_case_memory_ref(
    candidate: ReaderRepairFailureDiagnosticCandidate,
    *,
    version: int,
) -> str:
    return reader_repair_case_memory_ref(candidate.repair_case, version=version)


def _nested_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, Mapping):
            for key, item in current.items():
                keys.add(str(key).casefold())
                pending.append(item)
        elif isinstance(current, Sequence) and not isinstance(
            current,
            (str, bytes, bytearray),
        ):
            pending.extend(current)
    return keys


def _deep_mutable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _deep_mutable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_deep_mutable(item) for item in value]
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty trimmed text")
    return value


def _require_checksum(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _CHECKSUM_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be sha256:<64 lowercase hex>")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return value


def _exact_mapping(
    value: Any,
    expected: set[str],
    model_name: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{model_name} fields are invalid")
    return dict(value)


__all__ = [
    "READER_REPAIR_FAILURE_DIAGNOSTIC_EFFECT_KIND",
    "READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_ID",
    "READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_REF",
    "READER_REPAIR_FAILURE_DIAGNOSTIC_HANDLER_VERSION",
    "READER_REPAIR_FAILURE_DIAGNOSTIC_SCHEMA_VERSION",
    "READER_REPAIR_FAILURE_DIAGNOSTIC_TERMINAL_ACTION",
    "ReaderRepairFailureDiagnosticCandidate",
    "ReaderRepairFailureDiagnosticCommitPort",
    "ReaderRepairFailureDiagnosticCommitReceipt",
    "ReaderRepairFailureDiagnosticCommitRequest",
    "diagnostic_case_memory_ref",
]
