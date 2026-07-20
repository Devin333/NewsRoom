from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from framework.events.canonical import checksum_for
from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable


@dataclass(frozen=True, slots=True)
class HarnessSideEffectApprovalRequest:
    run_id: str
    step_id: str
    attempt: int
    effect_id: str
    candidate_checksum: str
    identity_scope_ref: str
    subject_scope_ref: str
    decision_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "step_id",
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
        _require_checksum(self.candidate_checksum, "candidate_checksum")
        _require_checksum(self.identity_scope_ref, "identity_scope_ref")
        _require_checksum(self.subject_scope_ref, "subject_scope_ref")

    @property
    def request_ref(self) -> str:
        return checksum_for(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "step_id": self.step_id,
            "attempt": self.attempt,
            "effect_id": self.effect_id,
            "candidate_checksum": self.candidate_checksum,
            "identity_scope_ref": self.identity_scope_ref,
            "subject_scope_ref": self.subject_scope_ref,
            "decision_version": self.decision_version,
        }


@dataclass(frozen=True, slots=True)
class HarnessSideEffectApprovalEvidence:
    approval_ref: str
    run_id: str
    step_id: str
    attempt: int
    effect_id: str
    candidate_checksum: str
    identity_scope_ref: str
    subject_scope_ref: str
    decision_version: str
    approved: bool = True
    status: str = "approved"
    metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        _require_checksum(self.approval_ref, "approval_ref")
        request = HarnessSideEffectApprovalRequest(
            run_id=self.run_id,
            step_id=self.step_id,
            attempt=self.attempt,
            effect_id=self.effect_id,
            candidate_checksum=self.candidate_checksum,
            identity_scope_ref=self.identity_scope_ref,
            subject_scope_ref=self.subject_scope_ref,
            decision_version=self.decision_version,
        )
        for field_name in (
            "run_id",
            "step_id",
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
            and self.step_id == request.step_id
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
            "step_id": self.step_id,
            "attempt": self.attempt,
            "effect_id": self.effect_id,
            "candidate_checksum": self.candidate_checksum,
            "identity_scope_ref": self.identity_scope_ref,
            "subject_scope_ref": self.subject_scope_ref,
            "decision_version": self.decision_version,
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
    return checksum_for(evidence.to_dict())


def _require_checksum(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise HarnessValidationError(f"{field_name} must be a sha256 reference")
    digest = value.removeprefix("sha256:")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise HarnessValidationError(f"{field_name} must be a sha256 reference")
    return value


def _approval_error(code: str, message: str, **details: Any) -> HarnessValidationError:
    return HarnessValidationError(message, code=code, details={"code": code, **details})


__all__ = [
    "HarnessSideEffectApprovalEvidence",
    "HarnessSideEffectApprovalRequest",
    "HarnessSideEffectApprovalResolver",
    "InMemoryHarnessSideEffectApprovalResolver",
    "approval_evidence_ref",
]
