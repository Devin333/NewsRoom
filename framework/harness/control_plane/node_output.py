from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from threading import RLock
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from framework.events.canonical import checksum_for
from framework.events.errors import EventCanonicalizationError
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.control_plane.graph_runtime import HarnessGraphActivity
from framework.harness.control_plane.graph_state import HarnessGraphReference
from framework.harness.graph.model import (
    HarnessContractKind,
    HarnessContractReference,
)
from framework.shared.time import ensure_utc, format_datetime, parse_datetime


HARNESS_NODE_OUTPUT_RESOURCE_SCHEMA = "newsroom.harness-node-output-resource/v1"
HARNESS_ADMITTED_GRAPH_ACTIVITY_SCHEMA = (
    "newsroom.harness-admitted-graph-activity/v1"
)
HARNESS_NODE_OUTPUT_LEASE_SCHEMA = "newsroom.harness-node-output-lease/v1"
HARNESS_NODE_OUTPUT_CANDIDATE_SCHEMA = "newsroom.harness-node-output-candidate/v1"
HARNESS_NODE_OUTPUT_STAGED_WRITE_SCHEMA = (
    "newsroom.harness-node-output-staged-write/v1"
)
HARNESS_NODE_OUTPUT_COMMIT_SCHEMA = "newsroom.harness-node-output-commit/v1"
HARNESS_COMMITTED_NODE_OUTPUT_RECEIPT_SCHEMA = (
    "newsroom.harness-committed-node-output-receipt/v1"
)

_CHECKSUM_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_OUTPUT_REFS = 64
_MAX_REF_NAME_LENGTH = 128


class HarnessNodeOutputAttemptStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    INDETERMINATE = "indeterminate"


class HarnessNodeOutputStaleOwnerError(HarnessValidationError):
    """Raised when a superseded activity attempt writes or commits output."""

    def __init__(
        self,
        *,
        resource_ref: str,
        owner_attempt_id: str,
        generation: int,
    ) -> None:
        super().__init__(
            "graph activity attempt no longer owns the node-output resource",
            code="graph_node_output_stale_owner",
            details={
                "resource_ref": resource_ref,
                "owner_attempt_id": owner_attempt_id,
                "generation": generation,
            },
        )


class HarnessNodeOutputCommitRejectedError(HarnessValidationError):
    """Raised when attempt determinacy does not authorize normal output."""


@dataclass(frozen=True, slots=True)
class HarnessNodeOutputResourceIdentity:
    run_id: str
    graph_ref: HarnessGraphReference
    node_id: str
    node_instance_id: str
    tenant_scope_ref: str | None = None
    identity_scope_ref: str | None = None
    subject_scope_ref: str | None = None
    schema_version: str = HARNESS_NODE_OUTPUT_RESOURCE_SCHEMA
    resource_ref: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _required_text(self.run_id, "run_id"))
        if not isinstance(self.graph_ref, HarnessGraphReference):
            raise TypeError("graph_ref must be HarnessGraphReference")
        object.__setattr__(self, "node_id", _required_text(self.node_id, "node_id"))
        object.__setattr__(
            self,
            "node_instance_id",
            _required_text(self.node_instance_id, "node_instance_id"),
        )
        for field_name in (
            "tenant_scope_ref",
            "identity_scope_ref",
            "subject_scope_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_checksum(getattr(self, field_name), field_name),
            )
        if self.schema_version != HARNESS_NODE_OUTPUT_RESOURCE_SCHEMA:
            raise HarnessValidationError(
                "unsupported node-output resource schema",
                code="unsupported_graph_node_output_resource_schema",
            )
        object.__setattr__(self, "resource_ref", checksum_for(self.checksum_projection()))

    @classmethod
    def for_activity(
        cls,
        activity: HarnessGraphActivity,
    ) -> HarnessNodeOutputResourceIdentity:
        _require_activity(activity)
        return cls(
            run_id=activity.run_id,
            graph_ref=activity.graph_ref,
            node_id=activity.node_id,
            node_instance_id=activity.node_instance_id,
            tenant_scope_ref=activity.tenant_scope_ref,
            identity_scope_ref=activity.identity_scope_ref,
            subject_scope_ref=activity.subject_scope_ref,
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "graph_ref": self.graph_ref.to_dict(),
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "tenant_scope_ref": self.tenant_scope_ref,
            "identity_scope_ref": self.identity_scope_ref,
            "subject_scope_ref": self.subject_scope_ref,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "resource_ref": self.resource_ref}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessNodeOutputResourceIdentity:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "run_id",
                "graph_ref",
                "node_id",
                "node_instance_id",
                "tenant_scope_ref",
                "identity_scope_ref",
                "subject_scope_ref",
                "resource_ref",
            },
            "node-output resource identity",
        )
        resource = cls(
            run_id=payload["run_id"],
            graph_ref=HarnessGraphReference.from_dict(payload["graph_ref"]),
            node_id=payload["node_id"],
            node_instance_id=payload["node_instance_id"],
            tenant_scope_ref=payload["tenant_scope_ref"],
            identity_scope_ref=payload["identity_scope_ref"],
            subject_scope_ref=payload["subject_scope_ref"],
            schema_version=payload["schema_version"],
        )
        if payload["resource_ref"] != resource.resource_ref:
            raise HarnessValidationError(
                "node-output resource checksum is invalid",
                code="graph_node_output_resource_checksum_invalid",
            )
        return resource


@dataclass(frozen=True, slots=True)
class HarnessAdmittedGraphActivityAttempt:
    activity_id: str
    activity_checksum: str
    owner_attempt_id: str
    operation_id: str
    operation_kind: str
    idempotency_key: str
    local_attempt_no: int
    parent_attempt_id: str | None
    retry_credit_id: str | None
    admitted_at: datetime
    schema_version: str = HARNESS_ADMITTED_GRAPH_ACTIVITY_SCHEMA
    admission_ref: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "activity_id",
            "owner_attempt_id",
            "operation_id",
            "operation_kind",
            "idempotency_key",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "activity_checksum",
            _checksum(self.activity_checksum, "activity_checksum"),
        )
        object.__setattr__(
            self,
            "local_attempt_no",
            _positive_int(self.local_attempt_no, "local_attempt_no"),
        )
        for field_name in ("parent_attempt_id", "retry_credit_id"):
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "admitted_at",
            _datetime(self.admitted_at, "admitted_at"),
        )
        if self.schema_version != HARNESS_ADMITTED_GRAPH_ACTIVITY_SCHEMA:
            raise HarnessValidationError(
                "unsupported admitted Graph activity schema",
                code="unsupported_admitted_graph_activity_schema",
            )
        object.__setattr__(self, "admission_ref", checksum_for(self.checksum_projection()))

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "activity_id": self.activity_id,
            "activity_checksum": self.activity_checksum,
            "owner_attempt_id": self.owner_attempt_id,
            "operation_id": self.operation_id,
            "operation_kind": self.operation_kind,
            "idempotency_key": self.idempotency_key,
            "local_attempt_no": self.local_attempt_no,
            "parent_attempt_id": self.parent_attempt_id,
            "retry_credit_id": self.retry_credit_id,
            "admitted_at": format_datetime(self.admitted_at),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "admission_ref": self.admission_ref}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessAdmittedGraphActivityAttempt:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "activity_id",
                "activity_checksum",
                "owner_attempt_id",
                "operation_id",
                "operation_kind",
                "idempotency_key",
                "local_attempt_no",
                "parent_attempt_id",
                "retry_credit_id",
                "admitted_at",
                "admission_ref",
            },
            "admitted Graph activity attempt",
        )
        admitted_at = _parse_datetime(payload["admitted_at"], "admitted_at")
        admission = cls(
            activity_id=payload["activity_id"],
            activity_checksum=payload["activity_checksum"],
            owner_attempt_id=payload["owner_attempt_id"],
            operation_id=payload["operation_id"],
            operation_kind=payload["operation_kind"],
            idempotency_key=payload["idempotency_key"],
            local_attempt_no=payload["local_attempt_no"],
            parent_attempt_id=payload["parent_attempt_id"],
            retry_credit_id=payload["retry_credit_id"],
            admitted_at=admitted_at,
            schema_version=payload["schema_version"],
        )
        if payload["admission_ref"] != admission.admission_ref:
            raise HarnessValidationError(
                "admitted Graph activity checksum is invalid",
                code="admitted_graph_activity_checksum_invalid",
            )
        return admission


@dataclass(frozen=True, slots=True)
class HarnessNodeOutputLease:
    resource: HarnessNodeOutputResourceIdentity
    activity_id: str
    activity_checksum: str
    admission_ref: str
    owner_attempt_id: str
    generation: int
    acquired_at: datetime
    previous_lease_ref: str | None = None
    schema_version: str = HARNESS_NODE_OUTPUT_LEASE_SCHEMA
    lease_ref: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.resource, HarnessNodeOutputResourceIdentity):
            raise TypeError("resource must be HarnessNodeOutputResourceIdentity")
        object.__setattr__(self, "activity_id", _required_text(self.activity_id, "activity_id"))
        object.__setattr__(
            self,
            "activity_checksum",
            _checksum(self.activity_checksum, "activity_checksum"),
        )
        object.__setattr__(self, "admission_ref", _checksum(self.admission_ref, "admission_ref"))
        object.__setattr__(
            self,
            "owner_attempt_id",
            _required_text(self.owner_attempt_id, "owner_attempt_id"),
        )
        object.__setattr__(self, "generation", _positive_int(self.generation, "generation"))
        object.__setattr__(self, "acquired_at", _datetime(self.acquired_at, "acquired_at"))
        object.__setattr__(
            self,
            "previous_lease_ref",
            _optional_checksum(self.previous_lease_ref, "previous_lease_ref"),
        )
        if self.schema_version != HARNESS_NODE_OUTPUT_LEASE_SCHEMA:
            raise HarnessValidationError(
                "unsupported node-output lease schema",
                code="unsupported_graph_node_output_lease_schema",
            )
        object.__setattr__(self, "lease_ref", checksum_for(self.checksum_projection()))

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "resource": self.resource.to_dict(),
            "activity_id": self.activity_id,
            "activity_checksum": self.activity_checksum,
            "admission_ref": self.admission_ref,
            "owner_attempt_id": self.owner_attempt_id,
            "generation": self.generation,
            "acquired_at": format_datetime(self.acquired_at),
            "previous_lease_ref": self.previous_lease_ref,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "lease_ref": self.lease_ref}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessNodeOutputLease:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "resource",
                "activity_id",
                "activity_checksum",
                "admission_ref",
                "owner_attempt_id",
                "generation",
                "acquired_at",
                "previous_lease_ref",
                "lease_ref",
            },
            "node-output lease",
        )
        acquired_at = _parse_datetime(payload["acquired_at"], "acquired_at")
        lease = cls(
            resource=HarnessNodeOutputResourceIdentity.from_dict(payload["resource"]),
            activity_id=payload["activity_id"],
            activity_checksum=payload["activity_checksum"],
            admission_ref=payload["admission_ref"],
            owner_attempt_id=payload["owner_attempt_id"],
            generation=payload["generation"],
            acquired_at=acquired_at,
            previous_lease_ref=payload["previous_lease_ref"],
            schema_version=payload["schema_version"],
        )
        if payload["lease_ref"] != lease.lease_ref:
            raise HarnessValidationError(
                "node-output lease checksum is invalid",
                code="graph_node_output_lease_checksum_invalid",
            )
        return lease


@dataclass(frozen=True, slots=True)
class HarnessNodeOutputCandidate:
    output_refs: Mapping[str, str]
    evidence_refs: tuple[str, ...]
    schema_version: str = HARNESS_NODE_OUTPUT_CANDIDATE_SCHEMA
    candidate_ref: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.output_refs, Mapping) or not self.output_refs:
            raise HarnessValidationError(
                "node-output candidate requires output refs",
                code="graph_node_output_candidate_invalid",
            )
        if len(self.output_refs) > _MAX_OUTPUT_REFS:
            raise HarnessValidationError(
                "node-output candidate has too many output refs",
                code="graph_node_output_candidate_too_large",
            )
        normalized_refs: dict[str, str] = {}
        for name, reference in self.output_refs.items():
            normalized_name = _required_text(name, "output_ref name")
            if len(normalized_name) > _MAX_REF_NAME_LENGTH:
                raise HarnessValidationError(
                    "node-output ref name is too long",
                    code="graph_node_output_candidate_invalid",
                )
            if normalized_name in normalized_refs:
                raise HarnessValidationError(
                    "node-output candidate has duplicate normalized ref names",
                    code="graph_node_output_candidate_invalid",
                )
            normalized_refs[normalized_name] = _checksum(
                reference,
                f"output_refs.{normalized_name}",
            )
        if (
            isinstance(self.evidence_refs, (str, bytes, bytearray))
            or not isinstance(self.evidence_refs, Sequence)
            or len(self.evidence_refs) > _MAX_OUTPUT_REFS
        ):
            raise HarnessValidationError(
                "node-output candidate requires bounded evidence refs",
                code="graph_node_output_candidate_invalid",
            )
        evidence_refs = tuple(
            sorted({_checksum(value, "evidence_ref") for value in self.evidence_refs})
        )
        if not evidence_refs or len(evidence_refs) != len(self.evidence_refs):
            raise HarnessValidationError(
                "node-output candidate requires unique bounded evidence refs",
                code="graph_node_output_candidate_invalid",
            )
        if self.schema_version != HARNESS_NODE_OUTPUT_CANDIDATE_SCHEMA:
            raise HarnessValidationError(
                "unsupported node-output candidate schema",
                code="unsupported_graph_node_output_candidate_schema",
            )
        object.__setattr__(
            self,
            "output_refs",
            MappingProxyType(dict(sorted(normalized_refs.items()))),
        )
        object.__setattr__(self, "evidence_refs", evidence_refs)
        object.__setattr__(self, "candidate_ref", checksum_for(self.checksum_projection()))

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "output_refs": dict(self.output_refs),
            "evidence_refs": list(self.evidence_refs),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "candidate_ref": self.candidate_ref}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessNodeOutputCandidate:
        payload = _exact_mapping(
            value,
            {"schema_version", "output_refs", "evidence_refs", "candidate_ref"},
            "node-output candidate",
        )
        if not isinstance(payload["evidence_refs"], list):
            raise HarnessValidationError(
                "node-output candidate evidence refs must be a list",
                code="graph_node_output_candidate_invalid",
            )
        candidate = cls(
            output_refs=payload["output_refs"],
            evidence_refs=tuple(payload["evidence_refs"]),
            schema_version=payload["schema_version"],
        )
        if payload["candidate_ref"] != candidate.candidate_ref:
            raise HarnessValidationError(
                "node-output candidate checksum is invalid",
                code="graph_node_output_candidate_checksum_invalid",
            )
        return candidate


@dataclass(frozen=True, slots=True)
class HarnessNodeOutputStagedWrite:
    lease_ref: str
    resource_ref: str
    activity_id: str
    owner_attempt_id: str
    generation: int
    candidate: HarnessNodeOutputCandidate
    staged_at: datetime
    schema_version: str = HARNESS_NODE_OUTPUT_STAGED_WRITE_SCHEMA
    stage_ref: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in ("lease_ref", "resource_ref"):
            object.__setattr__(
                self,
                field_name,
                _checksum(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "activity_id", _required_text(self.activity_id, "activity_id"))
        object.__setattr__(
            self,
            "owner_attempt_id",
            _required_text(self.owner_attempt_id, "owner_attempt_id"),
        )
        object.__setattr__(self, "generation", _positive_int(self.generation, "generation"))
        if not isinstance(self.candidate, HarnessNodeOutputCandidate):
            raise TypeError("candidate must be HarnessNodeOutputCandidate")
        object.__setattr__(self, "staged_at", _datetime(self.staged_at, "staged_at"))
        if self.schema_version != HARNESS_NODE_OUTPUT_STAGED_WRITE_SCHEMA:
            raise HarnessValidationError(
                "unsupported node-output staged write schema",
                code="unsupported_graph_node_output_staged_write_schema",
            )
        object.__setattr__(self, "stage_ref", checksum_for(self.checksum_projection()))

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "lease_ref": self.lease_ref,
            "resource_ref": self.resource_ref,
            "activity_id": self.activity_id,
            "owner_attempt_id": self.owner_attempt_id,
            "generation": self.generation,
            "candidate": self.candidate.to_dict(),
            "staged_at": format_datetime(self.staged_at),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "stage_ref": self.stage_ref}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessNodeOutputStagedWrite:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "lease_ref",
                "resource_ref",
                "activity_id",
                "owner_attempt_id",
                "generation",
                "candidate",
                "staged_at",
                "stage_ref",
            },
            "node-output staged write",
        )
        staged_at = _parse_datetime(payload["staged_at"], "staged_at")
        staged = cls(
            lease_ref=payload["lease_ref"],
            resource_ref=payload["resource_ref"],
            activity_id=payload["activity_id"],
            owner_attempt_id=payload["owner_attempt_id"],
            generation=payload["generation"],
            candidate=HarnessNodeOutputCandidate.from_dict(payload["candidate"]),
            staged_at=staged_at,
            schema_version=payload["schema_version"],
        )
        if payload["stage_ref"] != staged.stage_ref:
            raise HarnessValidationError(
                "node-output staged write checksum is invalid",
                code="graph_node_output_stage_checksum_invalid",
            )
        return staged


@dataclass(frozen=True, slots=True)
class HarnessNodeOutputCommitGuard:
    attempt_status: HarnessNodeOutputAttemptStatus | str
    termination_confirmed: bool
    descendants_determinate: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attempt_status",
            HarnessNodeOutputAttemptStatus(self.attempt_status),
        )
        if not isinstance(self.termination_confirmed, bool):
            raise TypeError("termination_confirmed must be boolean")
        if not isinstance(self.descendants_determinate, bool):
            raise TypeError("descendants_determinate must be boolean")

    def assert_allows_normal_output(self) -> None:
        if not self.descendants_determinate or (
            self.attempt_status is HarnessNodeOutputAttemptStatus.INDETERMINATE
        ):
            raise HarnessNodeOutputCommitRejectedError(
                "indeterminate activity attempt cannot publish normal node output",
                code="graph_node_output_indeterminate",
            )
        if not self.termination_confirmed:
            raise HarnessNodeOutputCommitRejectedError(
                "unconfirmed activity termination cannot publish normal node output",
                code="graph_node_output_termination_unconfirmed",
            )
        if self.attempt_status is not HarnessNodeOutputAttemptStatus.SUCCEEDED:
            raise HarnessNodeOutputCommitRejectedError(
                "non-success activity attempt cannot publish normal node output",
                code="graph_node_output_attempt_not_succeeded",
                details={"attempt_status": self.attempt_status.value},
            )


@dataclass(frozen=True, slots=True)
class HarnessNodeOutputCommit:
    stage_ref: str
    lease_ref: str
    resource_ref: str
    activity_id: str
    owner_attempt_id: str
    generation: int
    candidate: HarnessNodeOutputCandidate
    committed_at: datetime
    schema_version: str = HARNESS_NODE_OUTPUT_COMMIT_SCHEMA
    commit_ref: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in ("stage_ref", "lease_ref", "resource_ref"):
            object.__setattr__(
                self,
                field_name,
                _checksum(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "activity_id", _required_text(self.activity_id, "activity_id"))
        object.__setattr__(
            self,
            "owner_attempt_id",
            _required_text(self.owner_attempt_id, "owner_attempt_id"),
        )
        object.__setattr__(self, "generation", _positive_int(self.generation, "generation"))
        if not isinstance(self.candidate, HarnessNodeOutputCandidate):
            raise TypeError("candidate must be HarnessNodeOutputCandidate")
        object.__setattr__(self, "committed_at", _datetime(self.committed_at, "committed_at"))
        if self.schema_version != HARNESS_NODE_OUTPUT_COMMIT_SCHEMA:
            raise HarnessValidationError(
                "unsupported node-output commit schema",
                code="unsupported_graph_node_output_commit_schema",
            )
        object.__setattr__(self, "commit_ref", checksum_for(self.checksum_projection()))

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "stage_ref": self.stage_ref,
            "lease_ref": self.lease_ref,
            "resource_ref": self.resource_ref,
            "activity_id": self.activity_id,
            "owner_attempt_id": self.owner_attempt_id,
            "generation": self.generation,
            "candidate": self.candidate.to_dict(),
            "committed_at": format_datetime(self.committed_at),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "commit_ref": self.commit_ref}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HarnessNodeOutputCommit:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "stage_ref",
                "lease_ref",
                "resource_ref",
                "activity_id",
                "owner_attempt_id",
                "generation",
                "candidate",
                "committed_at",
                "commit_ref",
            },
            "node-output commit",
        )
        committed_at = _parse_datetime(payload["committed_at"], "committed_at")
        commit = cls(
            stage_ref=payload["stage_ref"],
            lease_ref=payload["lease_ref"],
            resource_ref=payload["resource_ref"],
            activity_id=payload["activity_id"],
            owner_attempt_id=payload["owner_attempt_id"],
            generation=payload["generation"],
            candidate=HarnessNodeOutputCandidate.from_dict(payload["candidate"]),
            committed_at=committed_at,
            schema_version=payload["schema_version"],
        )
        if payload["commit_ref"] != commit.commit_ref:
            raise HarnessValidationError(
                "node-output commit checksum is invalid",
                code="graph_node_output_commit_checksum_invalid",
            )
        return commit


@dataclass(frozen=True, slots=True)
class HarnessCommittedNodeOutputReceipt:
    """Checksum-bound proof that one Graph output was resource-committed."""

    graph_definition_checksum: str
    binding_id: str
    receipt_input_key: str
    producer_activity_id: str
    producer_activity_ref: HarnessContractReference
    resource: HarnessNodeOutputResourceIdentity
    commit: HarnessNodeOutputCommit
    output_key: str
    schema_version: str = HARNESS_COMMITTED_NODE_OUTPUT_RECEIPT_SCHEMA
    output_ref: str = field(init=False)
    receipt_ref: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "graph_definition_checksum",
            _checksum(
                self.graph_definition_checksum,
                "graph_definition_checksum",
            ),
        )
        for field_name in (
            "binding_id",
            "receipt_input_key",
            "producer_activity_id",
            "output_key",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        if not isinstance(self.producer_activity_ref, HarnessContractReference):
            raise TypeError("producer_activity_ref must be HarnessContractReference")
        if (
            self.producer_activity_ref.contract_kind
            is not HarnessContractKind.ACTIVITY
        ):
            raise HarnessValidationError(
                "committed node-output receipt requires an activity reference",
                code="graph_committed_node_output_receipt_invalid",
            )
        if not isinstance(self.resource, HarnessNodeOutputResourceIdentity):
            raise TypeError("resource must be HarnessNodeOutputResourceIdentity")
        if not isinstance(self.commit, HarnessNodeOutputCommit):
            raise TypeError("commit must be HarnessNodeOutputCommit")
        if self.commit.resource_ref != self.resource.resource_ref:
            raise HarnessValidationError(
                "committed node-output receipt resource does not match its commit",
                code="graph_committed_node_output_receipt_resource_mismatch",
            )
        output_ref = self.commit.candidate.output_refs.get(self.output_key)
        if output_ref is None:
            raise HarnessValidationError(
                "committed node-output receipt references an uncommitted output",
                code="graph_committed_node_output_receipt_output_missing",
                details={"output_key": self.output_key},
            )
        if self.schema_version != HARNESS_COMMITTED_NODE_OUTPUT_RECEIPT_SCHEMA:
            raise HarnessValidationError(
                "unsupported committed node-output receipt schema",
                code="unsupported_graph_committed_node_output_receipt_schema",
            )
        object.__setattr__(self, "output_ref", output_ref)
        object.__setattr__(
            self,
            "receipt_ref",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "graph_definition_checksum": self.graph_definition_checksum,
            "binding_id": self.binding_id,
            "receipt_input_key": self.receipt_input_key,
            "producer_activity_id": self.producer_activity_id,
            "producer_activity_ref": self.producer_activity_ref.to_dict(),
            "resource": self.resource.to_dict(),
            "commit": self.commit.to_dict(),
            "output_key": self.output_key,
            "output_ref": self.output_ref,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "receipt_ref": self.receipt_ref}

    def assert_matches_payload(self, value: Any) -> None:
        try:
            payload_ref = checksum_for(value)
        except (EventCanonicalizationError, TypeError, ValueError) as exc:
            raise HarnessValidationError(
                "committed node-output payload must be canonical JSON",
                code="graph_committed_node_output_payload_invalid",
                details={"output_key": self.output_key},
            ) from exc
        if payload_ref != self.output_ref:
            raise HarnessValidationError(
                "committed node-output receipt does not match its business payload",
                code="graph_committed_node_output_payload_mismatch",
                details={"output_key": self.output_key},
            )

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> HarnessCommittedNodeOutputReceipt:
        payload = _exact_mapping(
            value,
            {
                "schema_version",
                "graph_definition_checksum",
                "binding_id",
                "receipt_input_key",
                "producer_activity_id",
                "producer_activity_ref",
                "resource",
                "commit",
                "output_key",
                "output_ref",
                "receipt_ref",
            },
            "committed node-output receipt",
        )
        receipt = cls(
            graph_definition_checksum=payload["graph_definition_checksum"],
            binding_id=payload["binding_id"],
            receipt_input_key=payload["receipt_input_key"],
            producer_activity_id=payload["producer_activity_id"],
            producer_activity_ref=HarnessContractReference.from_dict(
                payload["producer_activity_ref"]
            ),
            resource=HarnessNodeOutputResourceIdentity.from_dict(payload["resource"]),
            commit=HarnessNodeOutputCommit.from_dict(payload["commit"]),
            output_key=payload["output_key"],
            schema_version=payload["schema_version"],
        )
        if payload["output_ref"] != receipt.output_ref:
            raise HarnessValidationError(
                "committed node-output receipt output checksum is invalid",
                code="graph_committed_node_output_receipt_output_mismatch",
            )
        if payload["receipt_ref"] != receipt.receipt_ref:
            raise HarnessValidationError(
                "committed node-output receipt checksum is invalid",
                code="graph_committed_node_output_receipt_checksum_invalid",
            )
        return receipt


@runtime_checkable
class HarnessNodeOutputResourcePort(Protocol):
    def acquire_after_admission(
        self,
        activity: HarnessGraphActivity,
        admission: HarnessAdmittedGraphActivityAttempt,
    ) -> HarnessNodeOutputLease: ...

    def stage(
        self,
        lease: HarnessNodeOutputLease,
        candidate: HarnessNodeOutputCandidate,
        *,
        staged_at: datetime,
    ) -> HarnessNodeOutputStagedWrite: ...

    def commit(
        self,
        staged: HarnessNodeOutputStagedWrite,
        guard: HarnessNodeOutputCommitGuard,
        *,
        committed_at: datetime,
    ) -> HarnessNodeOutputCommit: ...

    def discard(self, staged: HarnessNodeOutputStagedWrite) -> bool: ...

    def revoke(self, lease: HarnessNodeOutputLease) -> bool: ...

    def current_lease(
        self,
        resource: HarnessNodeOutputResourceIdentity,
    ) -> HarnessNodeOutputLease | None: ...

    def committed_output(
        self,
        resource: HarnessNodeOutputResourceIdentity,
    ) -> HarnessNodeOutputCommit | None: ...


class InMemoryHarnessNodeOutputResource:
    """Atomic reference implementation; production composition must inject storage."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._generations: dict[str, int] = {}
        self._current_leases: dict[str, HarnessNodeOutputLease] = {}
        self._leases_by_admission: dict[str, HarnessNodeOutputLease] = {}
        self._leases_by_owner: dict[tuple[str, str], HarnessNodeOutputLease] = {}
        self._staged_by_lease: dict[str, HarnessNodeOutputStagedWrite] = {}
        self._staged_by_ref: dict[str, HarnessNodeOutputStagedWrite] = {}
        self._commits: dict[str, HarnessNodeOutputCommit] = {}

    def acquire_after_admission(
        self,
        activity: HarnessGraphActivity,
        admission: HarnessAdmittedGraphActivityAttempt,
    ) -> HarnessNodeOutputLease:
        _require_activity(activity)
        if not isinstance(admission, HarnessAdmittedGraphActivityAttempt):
            raise TypeError("admission must be HarnessAdmittedGraphActivityAttempt")
        mismatches = tuple(
            field_name
            for field_name, expected, actual in (
                ("activity_id", activity.activity_id, admission.activity_id),
                (
                    "activity_checksum",
                    activity.activity_checksum,
                    admission.activity_checksum,
                ),
                ("idempotency_key", activity.idempotency_key, admission.idempotency_key),
            )
            if expected != actual
        )
        if mismatches:
            raise HarnessValidationError(
                "admitted attempt does not match its Graph activity",
                code="graph_node_output_admission_mismatch",
                details={"mismatches": list(mismatches)},
            )
        resource = HarnessNodeOutputResourceIdentity.for_activity(activity)
        with self._lock:
            if resource.resource_ref in self._commits:
                raise HarnessValidationError(
                    "node-output resource is already committed",
                    code="graph_node_output_already_committed",
                    details={"resource_ref": resource.resource_ref},
                )
            current = self._current_leases.get(resource.resource_ref)
            prior_admission = self._leases_by_admission.get(admission.admission_ref)
            if prior_admission is not None:
                if current == prior_admission:
                    return prior_admission
                raise HarnessNodeOutputStaleOwnerError(
                    resource_ref=resource.resource_ref,
                    owner_attempt_id=prior_admission.owner_attempt_id,
                    generation=prior_admission.generation,
                )
            owner_key = (resource.resource_ref, admission.owner_attempt_id)
            prior_owner = self._leases_by_owner.get(owner_key)
            if prior_owner is not None:
                if prior_owner.admission_ref != admission.admission_ref:
                    raise HarnessValidationError(
                        "node-output owner attempt identity is immutable",
                        code="graph_node_output_owner_identity_conflict",
                    )
                if current == prior_owner:
                    return prior_owner
                raise HarnessNodeOutputStaleOwnerError(
                    resource_ref=resource.resource_ref,
                    owner_attempt_id=prior_owner.owner_attempt_id,
                    generation=prior_owner.generation,
                )
            generation = self._generations.get(resource.resource_ref, 0) + 1
            lease = HarnessNodeOutputLease(
                resource=resource,
                activity_id=activity.activity_id,
                activity_checksum=activity.activity_checksum,
                admission_ref=admission.admission_ref,
                owner_attempt_id=admission.owner_attempt_id,
                generation=generation,
                acquired_at=admission.admitted_at,
                previous_lease_ref=current.lease_ref if current is not None else None,
            )
            if current is not None:
                superseded_stage = self._staged_by_lease.pop(
                    current.lease_ref,
                    None,
                )
                if superseded_stage is not None:
                    self._staged_by_ref.pop(superseded_stage.stage_ref, None)
            self._generations[resource.resource_ref] = generation
            self._current_leases[resource.resource_ref] = lease
            self._leases_by_admission[admission.admission_ref] = lease
            self._leases_by_owner[owner_key] = lease
            return lease

    def stage(
        self,
        lease: HarnessNodeOutputLease,
        candidate: HarnessNodeOutputCandidate,
        *,
        staged_at: datetime,
    ) -> HarnessNodeOutputStagedWrite:
        _require_lease(lease)
        if not isinstance(candidate, HarnessNodeOutputCandidate):
            raise TypeError("candidate must be HarnessNodeOutputCandidate")
        with self._lock:
            self._assert_current(lease)
            existing = self._staged_by_lease.get(lease.lease_ref)
            if existing is not None:
                if existing.candidate != candidate:
                    raise HarnessValidationError(
                        "node-output lease cannot stage conflicting candidates",
                        code="graph_node_output_stage_conflict",
                    )
                return existing
            staged = HarnessNodeOutputStagedWrite(
                lease_ref=lease.lease_ref,
                resource_ref=lease.resource.resource_ref,
                activity_id=lease.activity_id,
                owner_attempt_id=lease.owner_attempt_id,
                generation=lease.generation,
                candidate=candidate,
                staged_at=staged_at,
            )
            self._staged_by_lease[lease.lease_ref] = staged
            self._staged_by_ref[staged.stage_ref] = staged
            return staged

    def commit(
        self,
        staged: HarnessNodeOutputStagedWrite,
        guard: HarnessNodeOutputCommitGuard,
        *,
        committed_at: datetime,
    ) -> HarnessNodeOutputCommit:
        if not isinstance(staged, HarnessNodeOutputStagedWrite):
            raise TypeError("staged must be HarnessNodeOutputStagedWrite")
        if not isinstance(guard, HarnessNodeOutputCommitGuard):
            raise TypeError("guard must be HarnessNodeOutputCommitGuard")
        with self._lock:
            current = self._current_leases.get(staged.resource_ref)
            if current is None or (
                current.lease_ref != staged.lease_ref
                or current.owner_attempt_id != staged.owner_attempt_id
                or current.generation != staged.generation
            ):
                raise HarnessNodeOutputStaleOwnerError(
                    resource_ref=staged.resource_ref,
                    owner_attempt_id=staged.owner_attempt_id,
                    generation=staged.generation,
                )
            existing_commit = self._commits.get(staged.resource_ref)
            if existing_commit is not None:
                if existing_commit.stage_ref != staged.stage_ref:
                    raise HarnessValidationError(
                        "node-output resource cannot commit conflicting candidates",
                        code="graph_node_output_commit_conflict",
                    )
                return existing_commit
            persisted = self._staged_by_ref.get(staged.stage_ref)
            if persisted != staged:
                raise HarnessValidationError(
                    "node-output staged write is not owned by this resource",
                    code="graph_node_output_stage_missing",
                )
            guard.assert_allows_normal_output()
            commit = HarnessNodeOutputCommit(
                stage_ref=staged.stage_ref,
                lease_ref=staged.lease_ref,
                resource_ref=staged.resource_ref,
                activity_id=staged.activity_id,
                owner_attempt_id=staged.owner_attempt_id,
                generation=staged.generation,
                candidate=staged.candidate,
                committed_at=committed_at,
            )
            self._commits[staged.resource_ref] = commit
            return commit

    def discard(self, staged: HarnessNodeOutputStagedWrite) -> bool:
        if not isinstance(staged, HarnessNodeOutputStagedWrite):
            raise TypeError("staged must be HarnessNodeOutputStagedWrite")
        with self._lock:
            if staged.resource_ref in self._commits:
                return False
            existing = self._staged_by_ref.get(staged.stage_ref)
            if existing != staged:
                return False
            self._staged_by_ref.pop(staged.stage_ref, None)
            self._staged_by_lease.pop(staged.lease_ref, None)
            return True

    def revoke(self, lease: HarnessNodeOutputLease) -> bool:
        _require_lease(lease)
        with self._lock:
            if lease.resource.resource_ref in self._commits:
                return False
            current = self._current_leases.get(lease.resource.resource_ref)
            if current != lease:
                return False
            self._current_leases.pop(lease.resource.resource_ref, None)
            staged = self._staged_by_lease.pop(lease.lease_ref, None)
            if staged is not None:
                self._staged_by_ref.pop(staged.stage_ref, None)
            return True

    def current_lease(
        self,
        resource: HarnessNodeOutputResourceIdentity,
    ) -> HarnessNodeOutputLease | None:
        _require_resource(resource)
        with self._lock:
            return self._current_leases.get(resource.resource_ref)

    def committed_output(
        self,
        resource: HarnessNodeOutputResourceIdentity,
    ) -> HarnessNodeOutputCommit | None:
        _require_resource(resource)
        with self._lock:
            return self._commits.get(resource.resource_ref)

    def _assert_current(self, lease: HarnessNodeOutputLease) -> None:
        current = self._current_leases.get(lease.resource.resource_ref)
        if current != lease:
            raise HarnessNodeOutputStaleOwnerError(
                resource_ref=lease.resource.resource_ref,
                owner_attempt_id=lease.owner_attempt_id,
                generation=lease.generation,
            )


def _require_activity(activity: Any) -> HarnessGraphActivity:
    if not isinstance(activity, HarnessGraphActivity):
        raise TypeError("activity must be HarnessGraphActivity")
    return activity


def _require_resource(value: Any) -> HarnessNodeOutputResourceIdentity:
    if not isinstance(value, HarnessNodeOutputResourceIdentity):
        raise TypeError("resource must be HarnessNodeOutputResourceIdentity")
    return value


def _require_lease(value: Any) -> HarnessNodeOutputLease:
    if not isinstance(value, HarnessNodeOutputLease):
        raise TypeError("lease must be HarnessNodeOutputLease")
    return value


def _exact_mapping(
    value: Mapping[str, Any],
    expected: set[str],
    model: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise HarnessValidationError(
            f"{model} fields are invalid",
            code="graph_node_output_contract_invalid",
        )
    return dict(value)


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HarnessValidationError(
            f"{field_name} is required",
            code="graph_node_output_field_invalid",
        )
    return value.strip()


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _checksum(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _CHECKSUM_PATTERN.fullmatch(value) is None:
        raise HarnessValidationError(
            f"{field_name} must be a sha256 reference",
            code="graph_node_output_reference_invalid",
        )
    return value


def _optional_checksum(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _checksum(value, field_name)


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HarnessValidationError(
            f"{field_name} must be a positive integer",
            code="graph_node_output_generation_invalid",
        )
    return value


def _datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise HarnessValidationError(
            f"{field_name} must be a datetime",
            code="graph_node_output_time_invalid",
        )
    return ensure_utc(value)


def _parse_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise HarnessValidationError(
            f"{field_name} must be an ISO datetime",
            code="graph_node_output_time_invalid",
        )
    try:
        parsed = parse_datetime(value)
    except (TypeError, ValueError) as exc:
        raise HarnessValidationError(
            f"{field_name} must be an ISO datetime",
            code="graph_node_output_time_invalid",
        ) from exc
    if parsed is None:
        raise HarnessValidationError(
            f"{field_name} is required",
            code="graph_node_output_time_invalid",
        )
    return parsed


__all__ = [
    "HARNESS_ADMITTED_GRAPH_ACTIVITY_SCHEMA",
    "HARNESS_COMMITTED_NODE_OUTPUT_RECEIPT_SCHEMA",
    "HARNESS_NODE_OUTPUT_CANDIDATE_SCHEMA",
    "HARNESS_NODE_OUTPUT_COMMIT_SCHEMA",
    "HARNESS_NODE_OUTPUT_LEASE_SCHEMA",
    "HARNESS_NODE_OUTPUT_RESOURCE_SCHEMA",
    "HARNESS_NODE_OUTPUT_STAGED_WRITE_SCHEMA",
    "HarnessAdmittedGraphActivityAttempt",
    "HarnessCommittedNodeOutputReceipt",
    "HarnessNodeOutputAttemptStatus",
    "HarnessNodeOutputCandidate",
    "HarnessNodeOutputCommit",
    "HarnessNodeOutputCommitGuard",
    "HarnessNodeOutputCommitRejectedError",
    "HarnessNodeOutputLease",
    "HarnessNodeOutputResourceIdentity",
    "HarnessNodeOutputResourcePort",
    "HarnessNodeOutputStagedWrite",
    "HarnessNodeOutputStaleOwnerError",
    "InMemoryHarnessNodeOutputResource",
]
