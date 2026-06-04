from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import to_jsonable
from framework.shared.time import format_datetime, utc_now


class SkillCandidateStatus(StrEnum):
    PROPOSED = "proposed"
    VALIDATING = "validating"
    READY_FOR_EVAL = "ready_for_eval"
    REJECTED = "rejected"
    EVALUATED = "evaluated"


class SkillPromotionStatus(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REPAIR = "needs_repair"


@dataclass(frozen=True)
class SkillVersionRef:
    skill_id: str
    version: str
    package_ref: str | None = None

    def __post_init__(self) -> None:
        if not str(self.skill_id).strip():
            raise HarnessValidationError("skill_id is required")
        if not str(self.version).strip():
            raise HarnessValidationError("version is required")
        object.__setattr__(self, "skill_id", str(self.skill_id))
        object.__setattr__(self, "version", str(self.version))

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "version": self.version,
            "package_ref": self.package_ref,
        }


@dataclass(frozen=True)
class SkillExperience:
    experience_id: str
    source: str
    summary: str
    evidence_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not str(self.experience_id).strip():
            raise HarnessValidationError("experience_id is required")
        if not str(self.source).strip():
            raise HarnessValidationError("source is required")
        if not str(self.summary).strip():
            raise HarnessValidationError("summary is required")
        object.__setattr__(self, "evidence_refs", tuple(str(ref) for ref in self.evidence_refs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "source": self.source,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "metadata": to_jsonable(self.metadata),
            "created_at": format_datetime(self.created_at),
        }


@dataclass(frozen=True)
class SkillPatchSet:
    patch_id: str
    target: SkillVersionRef
    operations: tuple[dict[str, Any], ...]
    rationale: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.patch_id).strip():
            raise HarnessValidationError("patch_id is required")
        if not isinstance(self.target, SkillVersionRef):
            raise HarnessValidationError("target must be SkillVersionRef")
        if not self.operations:
            raise HarnessValidationError("operations are required")
        object.__setattr__(self, "operations", tuple(dict(operation) for operation in self.operations))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "target": self.target.to_dict(),
            "operations": to_jsonable(list(self.operations)),
            "rationale": self.rationale,
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class SkillCandidate:
    candidate_id: str
    base_version: SkillVersionRef
    patch_set: SkillPatchSet
    experiences: tuple[SkillExperience, ...] = ()
    status: SkillCandidateStatus | str = SkillCandidateStatus.PROPOSED
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not str(self.candidate_id).strip():
            raise HarnessValidationError("candidate_id is required")
        if not isinstance(self.base_version, SkillVersionRef):
            raise HarnessValidationError("base_version must be SkillVersionRef")
        if not isinstance(self.patch_set, SkillPatchSet):
            raise HarnessValidationError("patch_set must be SkillPatchSet")
        if not all(isinstance(experience, SkillExperience) for experience in self.experiences):
            raise HarnessValidationError("experiences must be SkillExperience values")
        metadata = dict(self.metadata)
        forbidden = sorted({"auto_promote", "active", "skip_eval"}.intersection(metadata))
        if forbidden:
            raise HarnessValidationError(
                "SkillCandidate must not contain publication bypass fields",
                details={"forbidden": forbidden},
            )
        object.__setattr__(self, "status", SkillCandidateStatus(self.status))
        object.__setattr__(self, "experiences", tuple(self.experiences))
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "base_version": self.base_version.to_dict(),
            "patch_set": self.patch_set.to_dict(),
            "experiences": [experience.to_dict() for experience in self.experiences],
            "status": self.status.value,
            "metadata": to_jsonable(self.metadata),
            "created_at": format_datetime(self.created_at),
        }


@dataclass(frozen=True)
class SkillEvaluationResult:
    candidate_id: str
    passed: bool
    score: float
    eval_case_count: int
    issues: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.candidate_id).strip():
            raise HarnessValidationError("candidate_id is required")
        if not 0 <= self.score <= 1:
            raise HarnessValidationError("score must be between 0 and 1")
        if self.eval_case_count <= 0:
            raise HarnessValidationError("eval_case_count must be greater than zero")
        object.__setattr__(self, "issues", tuple(str(issue) for issue in self.issues))
        object.__setattr__(self, "metrics", dict(self.metrics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "passed": self.passed,
            "score": self.score,
            "eval_case_count": self.eval_case_count,
            "issues": list(self.issues),
            "metrics": to_jsonable(self.metrics),
        }


@dataclass(frozen=True)
class SkillPromotionDecision:
    candidate_id: str
    status: SkillPromotionStatus | str
    decided_by: str = "harness"
    reasons: tuple[str, ...] = ()
    required_release_version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    decided_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not str(self.candidate_id).strip():
            raise HarnessValidationError("candidate_id is required")
        if str(self.decided_by).strip() != "harness":
            raise HarnessValidationError("SkillPromotionDecision must be decided_by='harness'")
        object.__setattr__(self, "status", SkillPromotionStatus(self.status))
        object.__setattr__(self, "reasons", tuple(str(reason) for reason in self.reasons))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status.value,
            "decided_by": self.decided_by,
            "reasons": list(self.reasons),
            "required_release_version": self.required_release_version,
            "metadata": to_jsonable(self.metadata),
            "decided_at": format_datetime(self.decided_at),
        }


@dataclass(frozen=True)
class SkillRollbackPlan:
    release_id: str
    previous_version: SkillVersionRef | None
    triggers: tuple[str, ...]
    fallback_action: str = "halt_skill_use"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.release_id).strip():
            raise HarnessValidationError("release_id is required")
        if not self.triggers:
            raise HarnessValidationError("rollback triggers are required")
        if self.previous_version is not None and not isinstance(self.previous_version, SkillVersionRef):
            raise HarnessValidationError("previous_version must be SkillVersionRef")
        object.__setattr__(self, "triggers", tuple(str(trigger) for trigger in self.triggers))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "previous_version": self.previous_version.to_dict() if self.previous_version else None,
            "triggers": list(self.triggers),
            "fallback_action": self.fallback_action,
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class SkillRelease:
    release_id: str
    candidate_id: str
    version: SkillVersionRef
    rollback_plan: SkillRollbackPlan
    metadata: dict[str, Any] = field(default_factory=dict)
    released_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not str(self.release_id).strip():
            raise HarnessValidationError("release_id is required")
        if not str(self.candidate_id).strip():
            raise HarnessValidationError("candidate_id is required")
        if not isinstance(self.version, SkillVersionRef):
            raise HarnessValidationError("version must be SkillVersionRef")
        if not isinstance(self.rollback_plan, SkillRollbackPlan):
            raise HarnessValidationError("rollback_plan must be SkillRollbackPlan")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "candidate_id": self.candidate_id,
            "version": self.version.to_dict(),
            "rollback_plan": self.rollback_plan.to_dict(),
            "metadata": to_jsonable(self.metadata),
            "released_at": format_datetime(self.released_at),
        }


__all__ = [
    "SkillCandidate",
    "SkillCandidateStatus",
    "SkillEvaluationResult",
    "SkillExperience",
    "SkillPatchSet",
    "SkillPromotionDecision",
    "SkillPromotionStatus",
    "SkillRelease",
    "SkillRollbackPlan",
    "SkillVersionRef",
]
