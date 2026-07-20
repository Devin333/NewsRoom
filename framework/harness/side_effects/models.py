from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import stable_json_dumps, to_jsonable
from framework.shared.time import ensure_utc, format_datetime, parse_datetime, utc_now


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$")
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_AMBIGUOUS_VERSIONS = frozenset({"current", "default", "latest", "stable"})


class HarnessSideEffectOrigin(StrEnum):
    WORKER = "worker"
    CONTROLLER_TERMINAL = "controller_terminal"


class HarnessSideEffectDisposition(StrEnum):
    CANDIDATE = "candidate"
    PREPARED = "prepared"
    QUARANTINE = "quarantine"
    ACCEPTED = "accepted"


class HarnessSideEffectDecisionStatus(StrEnum):
    AUTHORIZED = "authorized"
    DENIED = "denied"


class HarnessSideEffectOutcomeStatus(StrEnum):
    COMMITTED = "committed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, order=True)
class HarnessSideEffectHandlerReference:
    handler_id: str
    version: str

    def __post_init__(self) -> None:
        handler_id = _identifier(self.handler_id, "handler_id")
        version = _version(self.version)
        object.__setattr__(self, "handler_id", handler_id)
        object.__setattr__(self, "version", version)

    @classmethod
    def parse(
        cls,
        value: str | Mapping[str, Any] | HarnessSideEffectHandlerReference,
    ) -> HarnessSideEffectHandlerReference:
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            return cls(
                handler_id=value.get("handler_id"),
                version=value.get("version"),
            )
        if not isinstance(value, str) or value.count("@") != 1:
            raise _validation_error(
                "invalid_side_effect_handler_reference",
                "side-effect handler reference must use '<handler-id>@<version>'",
                reference=value,
            )
        handler_id, version = value.split("@", maxsplit=1)
        return cls(handler_id=handler_id, version=version)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessSideEffectHandlerReference:
        return cls.parse(value)

    def to_dict(self) -> dict[str, str]:
        return {"handler_id": self.handler_id, "version": self.version}

    def __str__(self) -> str:
        return f"{self.handler_id}@{self.version}"


HarnessSideEffectHandlerRef = HarnessSideEffectHandlerReference


@dataclass(frozen=True, slots=True)
class HarnessSideEffectIntent:
    effect_id: str
    kind: str
    run_id: str
    origin: HarnessSideEffectOrigin | str
    atomic_group: str
    identity_scope_ref: str
    subject_scope_ref: str
    attempt: int = 1
    step_id: str | None = None
    terminal_action: str | None = None
    worker_result_ref: str | None = None
    source_intent_ref: str | None = None
    candidate_checksum: str | None = None
    state_checksum: str | None = None
    completion_input_ref: str | None = None
    handler: HarnessSideEffectHandlerReference | str | Mapping[str, Any] | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    candidate_refs: tuple[str, ...] = ()
    idempotency_key: str | None = None
    retention_until: datetime | None = None
    schema_version: str = "newsroom.harness-side-effect-intent/v1"
    checksum: str | None = None

    def __post_init__(self) -> None:
        effect_id = _identifier(self.effect_id, "effect_id")
        kind = _identifier(self.kind, "kind")
        run_id = _required_text(self.run_id, "run_id")
        origin = _enum(HarnessSideEffectOrigin, self.origin, "origin")
        atomic_group = _identifier(self.atomic_group, "atomic_group")
        identity_scope_ref = _checksum(self.identity_scope_ref, "identity_scope_ref")
        subject_scope_ref = _checksum(self.subject_scope_ref, "subject_scope_ref")
        attempt = _positive_int(self.attempt, "attempt")
        handler = None if self.handler is None else HarnessSideEffectHandlerReference.parse(self.handler)
        payload = _immutable_mapping(self.payload, "payload")
        candidate_refs = _candidate_refs(self.candidate_refs)
        retention_until = _optional_datetime(self.retention_until, "retention_until")

        step_id = _optional_text(self.step_id, "step_id")
        terminal_action = _optional_text(self.terminal_action, "terminal_action")
        worker_result_ref = _optional_text(self.worker_result_ref, "worker_result_ref")
        source_intent_ref = _optional_checksum(self.source_intent_ref, "source_intent_ref")
        candidate_checksum = _optional_checksum(self.candidate_checksum, "candidate_checksum")
        state_checksum = _optional_checksum(self.state_checksum, "state_checksum")
        completion_input_ref = _optional_checksum(
            self.completion_input_ref,
            "completion_input_ref",
        )
        if origin is HarnessSideEffectOrigin.WORKER:
            if step_id is None or worker_result_ref is None or candidate_checksum is None:
                raise _validation_error(
                    "invalid_worker_side_effect_identity",
                    "worker side-effect intent requires step, worker-result, and candidate identities",
                    effect_id=effect_id,
                )
            if terminal_action is not None or state_checksum is not None or completion_input_ref is not None:
                raise _validation_error(
                    "worker_terminal_identity_forbidden",
                    "worker side-effect intent cannot carry controller-terminal identity",
                    effect_id=effect_id,
                )
        else:
            if terminal_action is None or state_checksum is None or completion_input_ref is None:
                raise _validation_error(
                    "invalid_terminal_side_effect_identity",
                    "controller-terminal intent requires terminal action, state, and completion identities",
                    effect_id=effect_id,
                )
            if step_id is not None or worker_result_ref is not None or candidate_checksum is not None:
                raise _validation_error(
                    "terminal_worker_identity_forbidden",
                    "controller-terminal intent cannot carry worker identity",
                    effect_id=effect_id,
                )

        idempotency_key = self.idempotency_key or f"harness-effect:{effect_id}"
        idempotency_key = _required_text(idempotency_key, "idempotency_key")
        schema_version = _required_text(self.schema_version, "schema_version")

        object.__setattr__(self, "effect_id", effect_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "atomic_group", atomic_group)
        object.__setattr__(self, "identity_scope_ref", identity_scope_ref)
        object.__setattr__(self, "subject_scope_ref", subject_scope_ref)
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "step_id", step_id)
        object.__setattr__(self, "terminal_action", terminal_action)
        object.__setattr__(self, "worker_result_ref", worker_result_ref)
        object.__setattr__(self, "source_intent_ref", source_intent_ref)
        object.__setattr__(self, "candidate_checksum", candidate_checksum)
        object.__setattr__(self, "state_checksum", state_checksum)
        object.__setattr__(self, "completion_input_ref", completion_input_ref)
        object.__setattr__(self, "handler", handler)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "candidate_refs", candidate_refs)
        object.__setattr__(self, "idempotency_key", idempotency_key)
        object.__setattr__(self, "retention_until", retention_until)
        object.__setattr__(self, "schema_version", schema_version)
        expected = checksum_for(self._checksum_payload())
        if self.checksum is not None and self.checksum != expected:
            raise _validation_error(
                "side_effect_intent_checksum_mismatch",
                "side-effect intent checksum does not match its canonical payload",
                effect_id=effect_id,
            )
        object.__setattr__(self, "checksum", expected)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessSideEffectIntent:
        if not isinstance(value, Mapping):
            raise HarnessValidationError("side-effect intent must be an object")
        return cls(
            effect_id=value.get("effect_id"),
            kind=value.get("kind"),
            run_id=value.get("run_id"),
            origin=value.get("origin"),
            atomic_group=value.get("atomic_group"),
            identity_scope_ref=value.get("identity_scope_ref"),
            subject_scope_ref=value.get("subject_scope_ref"),
            attempt=value.get("attempt", 1),
            step_id=value.get("step_id"),
            terminal_action=value.get("terminal_action"),
            worker_result_ref=value.get("worker_result_ref"),
            source_intent_ref=value.get("source_intent_ref"),
            candidate_checksum=value.get("candidate_checksum"),
            state_checksum=value.get("state_checksum"),
            completion_input_ref=value.get("completion_input_ref"),
            handler=value.get("handler"),
            payload=value.get("payload", {}),
            candidate_refs=tuple(value.get("candidate_refs", ())),
            idempotency_key=value.get("idempotency_key"),
            retention_until=parse_datetime(value.get("retention_until")),
            schema_version=value.get("schema_version", "newsroom.harness-side-effect-intent/v1"),
            checksum=value.get("checksum"),
        )

    def _checksum_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "effect_id": self.effect_id,
            "kind": self.kind,
            "origin": self.origin.value,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "terminal_action": self.terminal_action,
            "attempt": self.attempt,
            "worker_result_ref": self.worker_result_ref,
            "source_intent_ref": self.source_intent_ref,
            "candidate_checksum": self.candidate_checksum,
            "state_checksum": self.state_checksum,
            "completion_input_ref": self.completion_input_ref,
            "handler": None if self.handler is None else self.handler.to_dict(),
            "payload": to_jsonable(self.payload),
            "candidate_refs": list(self.candidate_refs),
            "atomic_group": self.atomic_group,
            "identity_scope_ref": self.identity_scope_ref,
            "subject_scope_ref": self.subject_scope_ref,
            "idempotency_key": self.idempotency_key,
            "retention_until": format_datetime(self.retention_until),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._checksum_payload(), "checksum": self.checksum}


@dataclass(frozen=True, slots=True)
class HarnessSideEffectDecision:
    decision_id: str
    intent_ref: str
    effect_id: str
    kind: str
    origin: HarnessSideEffectOrigin | str
    run_id: str
    handler: HarnessSideEffectHandlerReference | str | Mapping[str, Any]
    identity_scope_ref: str
    subject_scope_ref: str
    atomic_group: str
    idempotency_key: str
    command_ordinal: int
    causation_id: str
    disposition: HarnessSideEffectDisposition | str
    status: HarnessSideEffectDecisionStatus | str = HarnessSideEffectDecisionStatus.AUTHORIZED
    step_id: str | None = None
    terminal_action: str | None = None
    attempt: int = 1
    worker_result_ref: str | None = None
    terminal_state_ref: str | None = None
    gate_refs: tuple[str, ...] = ()
    gate_result_refs: tuple[str, ...] = ()
    aggregate_verdict_ref: str | None = None
    approval_evidence_ref: str | None = None
    budget_ref: str | None = None
    effect_attempt: int = 1
    effect_attempt_limit: int = 1
    reason_code: str = "authorized"
    decision_version: str = "1"
    decided_at: datetime = field(default_factory=utc_now)
    checksum: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "decision_id",
            "effect_id",
            "kind",
            "run_id",
            "identity_scope_ref",
            "subject_scope_ref",
            "atomic_group",
            "idempotency_key",
            "causation_id",
            "reason_code",
            "decision_version",
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), field_name))
        object.__setattr__(self, "intent_ref", _checksum(self.intent_ref, "intent_ref"))
        if isinstance(self.command_ordinal, bool) or not isinstance(self.command_ordinal, int) or self.command_ordinal < 0:
            raise HarnessValidationError("command_ordinal must be a non-negative integer")
        object.__setattr__(self, "origin", _enum(HarnessSideEffectOrigin, self.origin, "origin"))
        object.__setattr__(self, "handler", HarnessSideEffectHandlerReference.parse(self.handler))
        object.__setattr__(self, "identity_scope_ref", _checksum(self.identity_scope_ref, "identity_scope_ref"))
        object.__setattr__(self, "subject_scope_ref", _checksum(self.subject_scope_ref, "subject_scope_ref"))
        object.__setattr__(
            self,
            "disposition",
            _enum(HarnessSideEffectDisposition, self.disposition, "disposition"),
        )
        object.__setattr__(
            self,
            "status",
            _enum(HarnessSideEffectDecisionStatus, self.status, "status"),
        )
        object.__setattr__(self, "attempt", _positive_int(self.attempt, "attempt"))
        object.__setattr__(self, "effect_attempt", _positive_int(self.effect_attempt, "effect_attempt"))
        object.__setattr__(
            self,
            "effect_attempt_limit",
            _positive_int(self.effect_attempt_limit, "effect_attempt_limit"),
        )
        if self.effect_attempt > self.effect_attempt_limit:
            raise HarnessValidationError("effect_attempt must not exceed effect_attempt_limit")
        object.__setattr__(self, "step_id", _optional_text(self.step_id, "step_id"))
        object.__setattr__(self, "terminal_action", _optional_text(self.terminal_action, "terminal_action"))
        object.__setattr__(self, "worker_result_ref", _optional_text(self.worker_result_ref, "worker_result_ref"))
        object.__setattr__(
            self,
            "terminal_state_ref",
            _optional_checksum(self.terminal_state_ref, "terminal_state_ref"),
        )
        object.__setattr__(self, "gate_refs", _text_tuple(self.gate_refs, "gate_refs"))
        object.__setattr__(
            self,
            "gate_result_refs",
            _checksum_tuple(self.gate_result_refs, "gate_result_refs"),
        )
        for field_name in (
            "aggregate_verdict_ref",
            "approval_evidence_ref",
            "budget_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_checksum(getattr(self, field_name), field_name),
            )
        if self.origin is HarnessSideEffectOrigin.WORKER:
            if self.step_id is None or self.worker_result_ref is None or self.terminal_action is not None:
                raise HarnessValidationError("worker side-effect decision identity is incomplete")
        elif self.terminal_action is None or self.terminal_state_ref is None or self.step_id is not None:
            raise HarnessValidationError("controller-terminal side-effect decision identity is incomplete")
        if self.status is HarnessSideEffectDecisionStatus.AUTHORIZED and self.approval_evidence_ref is None:
            raise HarnessValidationError("authorized side-effect decision requires approval policy evidence")
        decided_at = _optional_datetime(self.decided_at, "decided_at")
        assert decided_at is not None
        object.__setattr__(self, "decided_at", decided_at)
        expected = checksum_for(self._checksum_payload())
        if self.checksum is not None and self.checksum != expected:
            raise HarnessValidationError("side-effect decision checksum mismatch")
        object.__setattr__(self, "checksum", expected)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessSideEffectDecision:
        if not isinstance(value, Mapping):
            raise HarnessValidationError("side-effect decision must be an object")
        return cls(
            decision_id=value.get("decision_id"),
            intent_ref=value.get("intent_ref"),
            effect_id=value.get("effect_id"),
            kind=value.get("kind"),
            origin=value.get("origin"),
            run_id=value.get("run_id"),
            handler=value.get("handler"),
            identity_scope_ref=value.get("identity_scope_ref"),
            subject_scope_ref=value.get("subject_scope_ref"),
            atomic_group=value.get("atomic_group"),
            idempotency_key=value.get("idempotency_key"),
            command_ordinal=value.get("command_ordinal"),
            causation_id=value.get("causation_id"),
            disposition=value.get("disposition"),
            status=value.get("status", HarnessSideEffectDecisionStatus.AUTHORIZED),
            step_id=value.get("step_id"),
            terminal_action=value.get("terminal_action"),
            attempt=value.get("attempt", 1),
            worker_result_ref=value.get("worker_result_ref"),
            terminal_state_ref=value.get("terminal_state_ref"),
            gate_refs=tuple(value.get("gate_refs", ())),
            gate_result_refs=tuple(value.get("gate_result_refs", ())),
            aggregate_verdict_ref=value.get("aggregate_verdict_ref"),
            approval_evidence_ref=value.get("approval_evidence_ref"),
            budget_ref=value.get("budget_ref"),
            effect_attempt=value.get("effect_attempt", 1),
            effect_attempt_limit=value.get("effect_attempt_limit", 1),
            reason_code=value.get("reason_code", "authorized"),
            decision_version=value.get("decision_version", "1"),
            decided_at=parse_datetime(value.get("decided_at")) or utc_now(),
            checksum=value.get("checksum"),
        )

    def _checksum_payload(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "intent_ref": self.intent_ref,
            "effect_id": self.effect_id,
            "kind": self.kind,
            "origin": self.origin.value,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "terminal_action": self.terminal_action,
            "attempt": self.attempt,
            "handler": self.handler.to_dict(),
            "identity_scope_ref": self.identity_scope_ref,
            "subject_scope_ref": self.subject_scope_ref,
            "atomic_group": self.atomic_group,
            "idempotency_key": self.idempotency_key,
            "command_ordinal": self.command_ordinal,
            "causation_id": self.causation_id,
            "worker_result_ref": self.worker_result_ref,
            "terminal_state_ref": self.terminal_state_ref,
            "gate_refs": list(self.gate_refs),
            "gate_result_refs": list(self.gate_result_refs),
            "aggregate_verdict_ref": self.aggregate_verdict_ref,
            "approval_evidence_ref": self.approval_evidence_ref,
            "budget_ref": self.budget_ref,
            "effect_attempt": self.effect_attempt,
            "effect_attempt_limit": self.effect_attempt_limit,
            "disposition": self.disposition.value,
            "status": self.status.value,
            "reason_code": self.reason_code,
            "decision_version": self.decision_version,
            "decided_at": format_datetime(self.decided_at),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._checksum_payload(), "checksum": self.checksum}


HarnessSideEffectAuthorization = HarnessSideEffectDecision


@dataclass(frozen=True, slots=True)
class HarnessSideEffectOutcome:
    outcome_id: str
    effect_id: str
    decision_ref: str
    run_id: str
    kind: str
    handler: HarnessSideEffectHandlerReference | str | Mapping[str, Any]
    idempotency_key: str
    identity_scope_ref: str
    subject_scope_ref: str
    atomic_group: str
    disposition: HarnessSideEffectDisposition | str
    status: HarnessSideEffectOutcomeStatus | str = HarnessSideEffectOutcomeStatus.COMMITTED
    candidate_refs: tuple[str, ...] = ()
    public_refs: tuple[str, ...] = ()
    result_ref: str | None = None
    reason_code: str = "committed"
    committed_at: datetime = field(default_factory=utc_now)
    retention_until: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = "newsroom.harness-side-effect-outcome/v1"
    checksum: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "outcome_id",
            "effect_id",
            "run_id",
            "kind",
            "idempotency_key",
            "identity_scope_ref",
            "subject_scope_ref",
            "atomic_group",
            "reason_code",
            "schema_version",
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), field_name))
        object.__setattr__(self, "decision_ref", _checksum(self.decision_ref, "decision_ref"))
        object.__setattr__(self, "handler", HarnessSideEffectHandlerReference.parse(self.handler))
        object.__setattr__(self, "identity_scope_ref", _checksum(self.identity_scope_ref, "identity_scope_ref"))
        object.__setattr__(self, "subject_scope_ref", _checksum(self.subject_scope_ref, "subject_scope_ref"))
        object.__setattr__(
            self,
            "disposition",
            _enum(HarnessSideEffectDisposition, self.disposition, "disposition"),
        )
        object.__setattr__(
            self,
            "status",
            _enum(HarnessSideEffectOutcomeStatus, self.status, "status"),
        )
        object.__setattr__(self, "candidate_refs", _candidate_refs(self.candidate_refs))
        object.__setattr__(self, "public_refs", _candidate_refs(self.public_refs, field_name="public_refs"))
        object.__setattr__(self, "result_ref", _optional_checksum(self.result_ref, "result_ref"))
        object.__setattr__(self, "metadata", _immutable_mapping(self.metadata, "metadata"))
        committed_at = _optional_datetime(self.committed_at, "committed_at")
        assert committed_at is not None
        object.__setattr__(self, "committed_at", committed_at)
        object.__setattr__(
            self,
            "retention_until",
            _optional_datetime(self.retention_until, "retention_until"),
        )
        if self.disposition is HarnessSideEffectDisposition.ACCEPTED and not self.public_refs:
            raise HarnessValidationError("accepted side-effect outcome requires public refs")
        if self.disposition is not HarnessSideEffectDisposition.ACCEPTED and self.public_refs:
            raise HarnessValidationError("non-accepted side-effect outcome cannot expose public refs")
        expected = checksum_for(self._checksum_payload())
        if self.checksum is not None and self.checksum != expected:
            raise HarnessValidationError("side-effect outcome checksum mismatch")
        object.__setattr__(self, "checksum", expected)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessSideEffectOutcome:
        if not isinstance(value, Mapping):
            raise HarnessValidationError("side-effect outcome must be an object")
        return cls(
            outcome_id=value.get("outcome_id"),
            effect_id=value.get("effect_id"),
            decision_ref=value.get("decision_ref"),
            run_id=value.get("run_id"),
            kind=value.get("kind"),
            handler=value.get("handler"),
            idempotency_key=value.get("idempotency_key"),
            identity_scope_ref=value.get("identity_scope_ref"),
            subject_scope_ref=value.get("subject_scope_ref"),
            atomic_group=value.get("atomic_group"),
            disposition=value.get("disposition"),
            status=value.get("status", HarnessSideEffectOutcomeStatus.COMMITTED),
            candidate_refs=tuple(value.get("candidate_refs", ())),
            public_refs=tuple(value.get("public_refs", ())),
            result_ref=value.get("result_ref"),
            reason_code=value.get("reason_code", "committed"),
            committed_at=parse_datetime(value.get("committed_at")) or utc_now(),
            retention_until=parse_datetime(value.get("retention_until")),
            metadata=value.get("metadata", {}),
            schema_version=value.get("schema_version", "newsroom.harness-side-effect-outcome/v1"),
            checksum=value.get("checksum"),
        )

    def _checksum_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "outcome_id": self.outcome_id,
            "effect_id": self.effect_id,
            "decision_ref": self.decision_ref,
            "run_id": self.run_id,
            "kind": self.kind,
            "handler": self.handler.to_dict(),
            "idempotency_key": self.idempotency_key,
            "identity_scope_ref": self.identity_scope_ref,
            "subject_scope_ref": self.subject_scope_ref,
            "atomic_group": self.atomic_group,
            "disposition": self.disposition.value,
            "status": self.status.value,
            "candidate_refs": list(self.candidate_refs),
            "public_refs": list(self.public_refs),
            "result_ref": self.result_ref,
            "reason_code": self.reason_code,
            "committed_at": format_datetime(self.committed_at),
            "retention_until": format_datetime(self.retention_until),
            "metadata": to_jsonable(self.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._checksum_payload(), "checksum": self.checksum}


@dataclass(frozen=True, slots=True)
class HarnessTerminalSideEffectPolicy:
    policy_id: str
    version: str
    handler: HarnessSideEffectHandlerReference | str | Mapping[str, Any]
    kind: str
    requires_approval: bool
    retry_limit: int
    not_required_evidence_ref: str | None = None
    inherited_gate_refs: tuple[str, ...] = ()
    inherit_budget: bool = True
    disposition: HarnessSideEffectDisposition | str = HarnessSideEffectDisposition.ACCEPTED
    schema_version: str = "newsroom.harness-terminal-side-effect-policy/v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _identifier(self.policy_id, "policy_id"))
        object.__setattr__(self, "version", _version(self.version))
        object.__setattr__(self, "handler", HarnessSideEffectHandlerReference.parse(self.handler))
        object.__setattr__(self, "kind", _identifier(self.kind, "kind"))
        if not isinstance(self.requires_approval, bool):
            raise HarnessValidationError("requires_approval must be a boolean")
        object.__setattr__(self, "retry_limit", _positive_int(self.retry_limit, "retry_limit"))
        object.__setattr__(
            self,
            "not_required_evidence_ref",
            _optional_checksum(self.not_required_evidence_ref, "not_required_evidence_ref"),
        )
        if self.requires_approval and self.not_required_evidence_ref is not None:
            raise HarnessValidationError("approval-required terminal policy cannot pin not_required evidence")
        if not self.requires_approval and self.not_required_evidence_ref is None:
            raise HarnessValidationError("no-approval terminal policy requires pinned not_required evidence")
        object.__setattr__(
            self,
            "inherited_gate_refs",
            _text_tuple(self.inherited_gate_refs, "inherited_gate_refs"),
        )
        if not isinstance(self.inherit_budget, bool):
            raise HarnessValidationError("inherit_budget must be a boolean")
        if not self.inherit_budget:
            raise HarnessValidationError("terminal side-effect policy must inherit the run budget")
        object.__setattr__(
            self,
            "disposition",
            _enum(HarnessSideEffectDisposition, self.disposition, "disposition"),
        )
        if self.disposition is not HarnessSideEffectDisposition.ACCEPTED:
            raise HarnessValidationError("terminal side-effect policy must target accepted disposition")
        object.__setattr__(self, "schema_version", _required_text(self.schema_version, "schema_version"))

    @property
    def reference(self) -> str:
        return f"{self.policy_id}@{self.version}"

    @property
    def handler_ref(self) -> HarnessSideEffectHandlerReference:
        return self.handler

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessTerminalSideEffectPolicy:
        if not isinstance(value, Mapping):
            raise HarnessValidationError("terminal side-effect policy must be an object")
        expected = {
            "schema_version",
            "policy_id",
            "version",
            "handler",
            "kind",
            "requires_approval",
            "retry_limit",
            "not_required_evidence_ref",
            "inherited_gate_refs",
            "inherit_budget",
            "disposition",
        }
        if set(value) != expected:
            raise _validation_error(
                "invalid_terminal_side_effect_policy",
                "terminal side-effect policy fields are invalid",
                missing=sorted(expected.difference(value)),
                unexpected=sorted(set(value).difference(expected)),
            )
        return cls(
            schema_version=value.get("schema_version"),
            policy_id=value.get("policy_id"),
            version=value.get("version"),
            handler=value.get("handler"),
            kind=value.get("kind"),
            requires_approval=value.get("requires_approval"),
            retry_limit=value.get("retry_limit"),
            not_required_evidence_ref=value.get("not_required_evidence_ref"),
            inherited_gate_refs=tuple(value.get("inherited_gate_refs", ())),
            inherit_budget=value.get("inherit_budget"),
            disposition=value.get("disposition"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "version": self.version,
            "handler": self.handler.to_dict(),
            "kind": self.kind,
            "requires_approval": self.requires_approval,
            "retry_limit": self.retry_limit,
            "not_required_evidence_ref": self.not_required_evidence_ref,
            "inherited_gate_refs": list(self.inherited_gate_refs),
            "inherit_budget": self.inherit_budget,
            "disposition": self.disposition.value,
        }


def _identifier(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if _IDENTIFIER_PATTERN.fullmatch(text) is None:
        raise HarnessValidationError(f"{field_name} has an invalid format")
    return text


def _version(value: Any) -> str:
    text = _required_text(value, "version")
    if _VERSION_PATTERN.fullmatch(text) is None or text.casefold() in _AMBIGUOUS_VERSIONS:
        raise _validation_error(
            "invalid_side_effect_handler_version",
            "side-effect version must be exact and cannot use a moving alias",
            version=text,
        )
    return text


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise HarnessValidationError(f"{field_name} is required and must not contain surrounding whitespace")
    return value


def _optional_text(value: Any, field_name: str) -> str | None:
    return None if value is None else _required_text(value, field_name)


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HarnessValidationError(f"{field_name} must be a positive integer")
    return value


def _checksum(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name)
    if not text.startswith("sha256:"):
        raise HarnessValidationError(f"{field_name} must be a sha256 reference")
    digest = text.removeprefix("sha256:")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise HarnessValidationError(f"{field_name} must be a sha256 reference")
    return text


def _optional_checksum(value: Any, field_name: str) -> str | None:
    return None if value is None else _checksum(value, field_name)


def _checksum_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise HarnessValidationError(f"{field_name} must be an array")
    return tuple(_checksum(item, field_name) for item in value)


def _text_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise HarnessValidationError(f"{field_name} must be an array")
    return tuple(_required_text(item, field_name) for item in value)


def _candidate_refs(value: Any, *, field_name: str = "candidate_refs") -> tuple[str, ...]:
    refs = _text_tuple(value, field_name)
    if len(set(refs)) != len(refs):
        raise HarnessValidationError(f"{field_name} must not contain duplicates")
    return refs


def _immutable_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HarnessValidationError(f"{field_name} must be an object")
    try:
        stable_json_dumps(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HarnessValidationError(f"{field_name} must be canonical JSON") from exc
    return _freeze_mapping(value)


def _freeze_mapping(value: Mapping[Any, Any]) -> Mapping[str, Any]:
    return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return tuple(sorted((_freeze(item) for item in value), key=stable_json_dumps))
    return value


def _optional_datetime(value: Any, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise HarnessValidationError(f"{field_name} must be a timezone-aware datetime")
    return ensure_utc(value)


def _enum(enum_type, value: Any, field_name: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise HarnessValidationError(f"{field_name} is invalid") from exc


def _validation_error(code: str, message: str, **details: Any) -> HarnessValidationError:
    return HarnessValidationError(message, code=code, details={"code": code, **details})


__all__ = [
    "HarnessSideEffectAuthorization",
    "HarnessSideEffectDecision",
    "HarnessSideEffectDecisionStatus",
    "HarnessSideEffectDisposition",
    "HarnessSideEffectHandlerRef",
    "HarnessSideEffectHandlerReference",
    "HarnessSideEffectIntent",
    "HarnessSideEffectOrigin",
    "HarnessSideEffectOutcome",
    "HarnessSideEffectOutcomeStatus",
    "HarnessTerminalSideEffectPolicy",
]
