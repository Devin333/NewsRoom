from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.graph_identity import GraphExecutionIdentity, GraphRunIdentity
from framework.shared.json import to_jsonable


@dataclass(frozen=True, slots=True)
class HarnessSideEffectApprovalRequest:
    run_id: str
    graph_id: str
    graph_version: str
    graph_ref: str
    graph_checksum: str
    node_id: str | None
    node_instance_id: str | None
    activity_id: str | None
    attempt: int
    effect_id: str
    candidate_checksum: str
    identity_scope_ref: str
    subject_scope_ref: str
    decision_version: str
    step_id: str | None = None
    terminal_action: str | None = None
    schema_version: str = "newsroom.harness-side-effect-approval/v2"

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "effect_id",
            "identity_scope_ref",
            "subject_scope_ref",
            "decision_version",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise HarnessValidationError(f"{field_name} is required")
            object.__setattr__(self, field_name, value.strip())
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise HarnessValidationError("approval request attempt must be positive")
        terminal_action = _optional_text(self.terminal_action, "terminal_action")
        identity = _canonical_side_effect_identity(
            run_id=self.run_id,
            graph_id=self.graph_id,
            graph_version=self.graph_version,
            graph_ref=self.graph_ref,
            graph_checksum=self.graph_checksum,
            node_id=self.node_id,
            node_instance_id=self.node_instance_id,
            activity_id=self.activity_id,
            attempt=self.attempt,
        )
        worker_identity_present = isinstance(identity, GraphExecutionIdentity)
        if not worker_identity_present and terminal_action is None:
            raise HarnessValidationError(
                "approval request requires either Graph node/activity or terminal action"
            )
        if worker_identity_present and terminal_action is not None:
            raise HarnessValidationError(
                "approval request cannot mix worker and terminal identity"
            )
        for field_name in (
            "graph_id", "graph_version", "graph_ref", "graph_checksum", "run_id",
            "node_id", "node_instance_id", "activity_id", "attempt", "step_id",
        ):
            object.__setattr__(self, field_name, getattr(identity, field_name, None))
        object.__setattr__(self, "terminal_action", terminal_action)
        if self.schema_version != "newsroom.harness-side-effect-approval/v2":
            raise HarnessValidationError("active side-effect approval schema must use Graph v2")
        _require_checksum(self.candidate_checksum, "candidate_checksum")
        _require_checksum(self.identity_scope_ref, "identity_scope_ref")
        _require_checksum(self.subject_scope_ref, "subject_scope_ref")

    @property
    def request_ref(self) -> str:
        return checksum_for(self._canonical_dict())

    def _canonical_dict(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload.pop("step_id", None)
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_ref": self.graph_ref,
            "graph_checksum": self.graph_checksum,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "activity_id": self.activity_id,
            "attempt": self.attempt,
            "effect_id": self.effect_id,
            "candidate_checksum": self.candidate_checksum,
            "identity_scope_ref": self.identity_scope_ref,
            "subject_scope_ref": self.subject_scope_ref,
            "decision_version": self.decision_version,
            "step_id": self.step_id,
            "terminal_action": self.terminal_action,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class HarnessSideEffectApprovalEvidence:
    approval_ref: str
    run_id: str
    graph_id: str
    graph_version: str
    graph_ref: str
    graph_checksum: str
    node_id: str | None
    node_instance_id: str | None
    activity_id: str | None
    attempt: int
    effect_id: str
    candidate_checksum: str
    identity_scope_ref: str
    subject_scope_ref: str
    decision_version: str
    approved: bool = True
    status: str = "approved"
    metadata: Mapping[str, Any] | None = None
    step_id: str | None = None
    terminal_action: str | None = None
    schema_version: str = "newsroom.harness-side-effect-approval/v2"

    def __post_init__(self) -> None:
        _require_checksum(self.approval_ref, "approval_ref")
        request = HarnessSideEffectApprovalRequest(
            run_id=self.run_id,
            graph_id=self.graph_id,
            graph_version=self.graph_version,
            graph_ref=self.graph_ref,
            graph_checksum=self.graph_checksum,
            node_id=self.node_id,
            node_instance_id=self.node_instance_id,
            activity_id=self.activity_id,
            attempt=self.attempt,
            effect_id=self.effect_id,
            candidate_checksum=self.candidate_checksum,
            identity_scope_ref=self.identity_scope_ref,
            subject_scope_ref=self.subject_scope_ref,
            decision_version=self.decision_version,
            step_id=self.step_id,
            terminal_action=self.terminal_action,
            schema_version=self.schema_version,
        )
        for field_name in (
            "run_id",
            "graph_id",
            "graph_version",
            "graph_ref",
            "graph_checksum",
            "node_id",
            "node_instance_id",
            "activity_id",
            "step_id",
            "terminal_action",
            "effect_id",
            "candidate_checksum",
            "identity_scope_ref",
            "subject_scope_ref",
            "decision_version",
        ):
            object.__setattr__(self, field_name, getattr(request, field_name))
        if not isinstance(self.approved, bool):
            raise HarnessValidationError("approval evidence approved must be a boolean")
        if not isinstance(self.status, str) or not self.status.strip():
            raise HarnessValidationError("approval evidence status is required")
        object.__setattr__(self, "status", self.status.strip())
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def matches(self, request: HarnessSideEffectApprovalRequest) -> bool:
        return (
            self.approved
            and self.status == "approved"
            and self.run_id == request.run_id
            and self.graph_id == request.graph_id
            and self.graph_version == request.graph_version
            and self.graph_ref == request.graph_ref
            and self.graph_checksum == request.graph_checksum
            and self.node_id == request.node_id
            and self.node_instance_id == request.node_instance_id
            and self.activity_id == request.activity_id
            and self.terminal_action == request.terminal_action
            and self.attempt == request.attempt
            and self.effect_id == request.effect_id
            and self.candidate_checksum == request.candidate_checksum
            and self.identity_scope_ref == request.identity_scope_ref
            and self.subject_scope_ref == request.subject_scope_ref
            and self.decision_version == request.decision_version
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_ref": self.approval_ref,
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "graph_ref": self.graph_ref,
            "graph_checksum": self.graph_checksum,
            "node_id": self.node_id,
            "node_instance_id": self.node_instance_id,
            "activity_id": self.activity_id,
            "attempt": self.attempt,
            "effect_id": self.effect_id,
            "candidate_checksum": self.candidate_checksum,
            "identity_scope_ref": self.identity_scope_ref,
            "subject_scope_ref": self.subject_scope_ref,
            "decision_version": self.decision_version,
            "step_id": self.step_id,
            "terminal_action": self.terminal_action,
            "schema_version": self.schema_version,
            "approved": self.approved,
            "status": self.status,
            "metadata": to_jsonable(self.metadata),
        }


@runtime_checkable
class HarnessSideEffectApprovalResolver(Protocol):
    def resolve(
        self,
        request: HarnessSideEffectApprovalRequest,
        *,
        approval_ref: str,
    ) -> HarnessSideEffectApprovalEvidence:
        ...


class InMemoryHarnessSideEffectApprovalResolver:
    """Read-only evidence resolver used by contract tests and local composition."""

    def __init__(self, evidence: Iterable[HarnessSideEffectApprovalEvidence] = ()) -> None:
        self._evidence: dict[str, HarnessSideEffectApprovalEvidence] = {}
        for item in evidence:
            self.add(item)

    def add(self, evidence: HarnessSideEffectApprovalEvidence) -> None:
        if not isinstance(evidence, HarnessSideEffectApprovalEvidence):
            raise TypeError("evidence must be HarnessSideEffectApprovalEvidence")
        if evidence.approval_ref in self._evidence:
            raise HarnessValidationError("approval evidence reference is immutable")
        self._evidence[evidence.approval_ref] = evidence

    def resolve(
        self,
        request: HarnessSideEffectApprovalRequest,
        *,
        approval_ref: str,
    ) -> HarnessSideEffectApprovalEvidence:
        if not isinstance(request, HarnessSideEffectApprovalRequest):
            raise TypeError("request must be HarnessSideEffectApprovalRequest")
        evidence = self._evidence.get(approval_ref)
        if evidence is None:
            raise _approval_error(
                "side_effect_approval_missing",
                "side-effect approval evidence is unavailable",
                approval_ref=approval_ref,
            )
        if not evidence.matches(request):
            raise _approval_error(
                "side_effect_approval_mismatch",
                "side-effect approval evidence does not match the exact effect identity",
                approval_ref=approval_ref,
                request_ref=request.request_ref,
            )
        return evidence


def approval_evidence_ref(evidence: HarnessSideEffectApprovalEvidence) -> str:
    if not isinstance(evidence, HarnessSideEffectApprovalEvidence):
        raise TypeError("evidence must be HarnessSideEffectApprovalEvidence")
    payload = evidence.to_dict()
    payload.pop("step_id", None)
    return checksum_for(payload)


def _require_checksum(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise HarnessValidationError(f"{field_name} must be a sha256 reference")
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise HarnessValidationError(f"{field_name} must be a sha256 reference")
    return value


def _optional_text(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HarnessValidationError(f"{field_name} must be a non-blank string")
    return value.strip()


def _canonical_side_effect_identity(
    *,
    run_id: str,
    graph_id: str,
    graph_version: str,
    graph_ref: str,
    graph_checksum: str,
    node_id: str | None,
    node_instance_id: str | None,
    activity_id: str | None,
    attempt: int,
) -> GraphRunIdentity | GraphExecutionIdentity:
    physical = (node_id, node_instance_id, activity_id)
    if any(value is not None for value in physical) and not all(
        value is not None for value in physical
    ):
        raise HarnessValidationError(
            "side-effect identity must provide all physical Graph activity fields"
        )
    try:
        if all(value is not None for value in physical):
            return GraphExecutionIdentity(
                run_id=run_id,
                graph_id=graph_id,
                graph_version=graph_version,
                graph_ref=graph_ref,
                graph_checksum=graph_checksum,
                node_id=node_id,
                node_instance_id=node_instance_id,
                activity_id=activity_id,
                attempt=attempt,
            )
        return GraphRunIdentity(
            run_id=run_id,
            graph_id=graph_id,
            graph_version=graph_version,
            graph_ref=graph_ref,
            graph_checksum=graph_checksum,
        )
    except (TypeError, ValueError) as exc:
        raise HarnessValidationError(
            "side-effect identity is not a canonical Graph identity"
        ) from exc


def _approval_error(code: str, message: str, **details: Any) -> HarnessValidationError:
    return HarnessValidationError(message, code=code, details={"code": code, **details})


__all__ = [
    "HarnessSideEffectApprovalEvidence",
    "HarnessSideEffectApprovalRequest",
    "HarnessSideEffectApprovalResolver",
    "InMemoryHarnessSideEffectApprovalResolver",
    "approval_evidence_ref",
]
