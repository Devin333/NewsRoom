from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.shared.json import stable_json_dumps, to_jsonable
from framework.shared.time import format_datetime, utc_now


FORBIDDEN_SKILL_CANDIDATE_KEYS = frozenset({"auto_promote", "active", "skip_eval", "promote", "publish"})
FORBIDDEN_SKILL_PATCH_OPERATIONS = frozenset(
    {
        "write_arbitrary_file",
        "delete_package",
        "change_allowed_tools_to_high_risk_without_approval",
        "remove_required_quality_gate",
        "disable_schema_validation",
    }
)
ALLOWED_SKILL_PATCH_OPERATIONS = frozenset(
    {
        "add_section",
        "replace_section",
        "delete_section",
        "update_frontmatter_field",
        "update_prompt_file",
        "update_reference_file",
        "update_schema_file",
        "update_eval_case",
        "replace",
    }
)


class SkillCandidateStatus(StrEnum):
    DRAFT = "draft"
    STATIC_VALIDATING = "static_validating"
    STATIC_REJECTED = "static_rejected"
    EVAL_READY = "eval_ready"
    EVALUATING = "evaluating"
    EVAL_REJECTED = "eval_rejected"
    SANDBOX_READY = "sandbox_ready"
    SANDBOX_REJECTED = "sandbox_rejected"
    PROMOTION_PENDING = "promotion_pending"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"
    PROPOSED = "proposed"
    VALIDATING = "validating"
    READY_FOR_EVAL = "ready_for_eval"
    EVALUATED = "evaluated"


class SkillPromotionStatus(StrEnum):
    PROMOTE = "promote"
    REJECT = "reject"
    NEEDS_MORE_EVAL = "needs_more_eval"
    NEEDS_HUMAN_APPROVAL = "needs_human_approval"
    HALTED = "halted"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REPAIR = "needs_repair"


class SkillExperienceOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class SkillEvaluationSplit(StrEnum):
    TRAIN = "train"
    EVAL = "eval"
    HELD_OUT = "held_out"
    SANDBOX = "sandbox"


class SkillEvolutionStatus(StrEnum):
    RUNNING = "running"
    HALTED = "halted"
    SUCCEEDED_NOOP = "succeeded_noop"
    REJECTED = "rejected"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class SkillVersionRef:
    skill_name: str | None = None
    version: str = ""
    package_hash: str | None = None
    source_root: str | None = None
    status: str = "active"
    package_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: Any = field(default_factory=utc_now)
    skill_id: str | None = None

    def __post_init__(self) -> None:
        skill_name = self.skill_name or self.skill_id
        if not str(skill_name or "").strip():
            raise HarnessValidationError("skill_name is required")
        if not str(self.version).strip():
            raise HarnessValidationError("version is required")
        object.__setattr__(self, "skill_name", str(skill_name))
        object.__setattr__(self, "skill_id", str(skill_name))
        object.__setattr__(self, "version", str(self.version))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def immutable_ref(self) -> str:
        if self.package_hash:
            return f"skill://{self.skill_name}@{self.version}#{self.package_hash}"
        return self.package_ref or f"skill://{self.skill_name}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_name,
            "skill_name": self.skill_name,
            "version": self.version,
            "package_hash": self.package_hash,
            "source_root": self.source_root,
            "status": self.status,
            "package_ref": self.package_ref,
            "immutable_ref": self.immutable_ref,
            "metadata": to_jsonable(self.metadata),
            "created_at": format_datetime(self.created_at),
        }


@dataclass(frozen=True)
class SkillExperience:
    experience_id: str
    run_id: str | None = None
    step_id: str | None = None
    skill_name: str | None = None
    skill_version: str | None = None
    domain: str | None = None
    task_type: str | None = None
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    transcript_refs: tuple[str, ...] = ()
    gate_results: tuple[dict[str, Any], ...] = ()
    score: float | None = None
    outcome: SkillExperienceOutcome | str = SkillExperienceOutcome.UNKNOWN
    failure_tags: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    source: str | None = None
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not str(self.experience_id).strip():
            raise HarnessValidationError("experience_id is required")
        source = self.source or self.domain or "harness_run"
        summary = self.summary or self.metadata.get("summary")
        if not str(source).strip():
            raise HarnessValidationError("source is required")
        if not str(summary or "").strip():
            raise HarnessValidationError("summary is required")
        if self.score is not None and not 0 <= self.score <= 1:
            raise HarnessValidationError("score must be between 0 and 1")
        object.__setattr__(self, "source", str(source))
        object.__setattr__(self, "summary", str(summary))
        object.__setattr__(self, "outcome", SkillExperienceOutcome(self.outcome))
        object.__setattr__(self, "input_refs", tuple(str(ref) for ref in self.input_refs))
        object.__setattr__(self, "output_refs", tuple(str(ref) for ref in self.output_refs))
        object.__setattr__(self, "transcript_refs", tuple(str(ref) for ref in self.transcript_refs))
        object.__setattr__(self, "gate_results", tuple(dict(result) for result in self.gate_results))
        object.__setattr__(self, "failure_tags", tuple(str(tag) for tag in self.failure_tags))
        object.__setattr__(self, "evidence_refs", tuple(str(ref) for ref in self.evidence_refs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "experience_id": self.experience_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "skill_name": self.skill_name,
            "skill_version": self.skill_version,
            "domain": self.domain,
            "task_type": self.task_type,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "transcript_refs": list(self.transcript_refs),
            "gate_results": to_jsonable(list(self.gate_results)),
            "score": self.score,
            "outcome": self.outcome.value,
            "failure_tags": list(self.failure_tags),
            "evidence_refs": list(self.evidence_refs),
            "source": self.source,
            "summary": self.summary,
            "metadata": to_jsonable(self.metadata),
            "created_at": format_datetime(self.created_at),
        }


@dataclass(frozen=True)
class SkillExperiencePool:
    pool_id: str
    skill_name: str
    experiences: tuple[SkillExperience, ...]
    held_out_experience_ids: tuple[str, ...] = ()
    selection_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.pool_id).strip():
            raise HarnessValidationError("pool_id is required")
        if not str(self.skill_name).strip():
            raise HarnessValidationError("skill_name is required")
        if not self.experiences:
            raise HarnessValidationError("experience pool requires at least one experience")
        if not all(isinstance(item, SkillExperience) for item in self.experiences):
            raise HarnessValidationError("experiences must be SkillExperience values")
        object.__setattr__(self, "experiences", tuple(self.experiences))
        object.__setattr__(self, "held_out_experience_ids", tuple(str(item) for item in self.held_out_experience_ids))
        object.__setattr__(self, "selection_policy", dict(self.selection_policy))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool_id": self.pool_id,
            "skill_name": self.skill_name,
            "experiences": [item.to_dict() for item in self.experiences],
            "held_out_experience_ids": list(self.held_out_experience_ids),
            "selection_policy": to_jsonable(self.selection_policy),
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class SkillEvolutionBudget:
    max_evolution_epochs: int = 1
    max_candidates_per_run: int = 2
    max_patch_operations: int = 6
    max_changed_files: int = 4
    max_rejected_candidates_to_load: int = 4
    max_eval_cases: int = 8
    max_sandbox_runs: int = 1

    def __post_init__(self) -> None:
        for field_name in (
            "max_evolution_epochs",
            "max_candidates_per_run",
            "max_patch_operations",
            "max_changed_files",
            "max_rejected_candidates_to_load",
            "max_eval_cases",
            "max_sandbox_runs",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or value < 0:
                raise HarnessValidationError(f"{field_name} must be a non-negative integer")
        if self.max_evolution_epochs <= 0:
            raise HarnessValidationError("max_evolution_epochs must be greater than zero")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_evolution_epochs": self.max_evolution_epochs,
            "max_candidates_per_run": self.max_candidates_per_run,
            "max_patch_operations": self.max_patch_operations,
            "max_changed_files": self.max_changed_files,
            "max_rejected_candidates_to_load": self.max_rejected_candidates_to_load,
            "max_eval_cases": self.max_eval_cases,
            "max_sandbox_runs": self.max_sandbox_runs,
        }


@dataclass(frozen=True)
class SkillEvolutionRunSpec:
    run_id: str
    skill_name: str
    base_version: SkillVersionRef
    experience_pool_ref: str
    budget: SkillEvolutionBudget = field(default_factory=SkillEvolutionBudget)
    policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("run_id", "skill_name", "experience_pool_ref"):
            if not str(getattr(self, field_name)).strip():
                raise HarnessValidationError(f"{field_name} is required")
        if not isinstance(self.base_version, SkillVersionRef):
            raise HarnessValidationError("base_version must be SkillVersionRef")
        if not isinstance(self.budget, SkillEvolutionBudget):
            raise HarnessValidationError("budget must be SkillEvolutionBudget")
        object.__setattr__(self, "policy", dict(self.policy))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "skill_name": self.skill_name,
            "base_version": self.base_version.to_dict(),
            "experience_pool_ref": self.experience_pool_ref,
            "budget": self.budget.to_dict(),
            "policy": to_jsonable(self.policy),
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class SkillEvolutionState:
    run_id: str
    status: SkillEvolutionStatus | str
    epochs_used: int = 0
    candidates_created: int = 0
    eval_cases_used: int = 0
    sandbox_runs_used: int = 0
    current_candidate_id: str | None = None
    transcript_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.run_id).strip():
            raise HarnessValidationError("run_id is required")
        object.__setattr__(self, "status", SkillEvolutionStatus(self.status))
        object.__setattr__(self, "transcript_refs", tuple(str(ref) for ref in self.transcript_refs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "epochs_used": self.epochs_used,
            "candidates_created": self.candidates_created,
            "eval_cases_used": self.eval_cases_used,
            "sandbox_runs_used": self.sandbox_runs_used,
            "current_candidate_id": self.current_candidate_id,
            "transcript_refs": list(self.transcript_refs),
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class SkillPatchOperation:
    op: str
    path: str
    value: Any | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.op).strip():
            raise HarnessValidationError("patch operation op is required")
        if not str(self.path).strip():
            raise HarnessValidationError("patch operation path is required")
        object.__setattr__(self, "op", str(self.op))
        object.__setattr__(self, "path", str(self.path))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SkillPatchOperation":
        return cls(
            op=str(payload.get("op", payload.get("operation", ""))),
            path=str(payload.get("path", "")),
            value=payload.get("value"),
            reason=payload.get("reason"),
            metadata=dict(payload.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "path": self.path,
            "value": to_jsonable(self.value),
            "reason": self.reason,
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class SkillPatchSet:
    candidate_id: str | None = None
    base_skill: SkillVersionRef | None = None
    operations: tuple[SkillPatchOperation | dict[str, Any], ...] = ()
    patch_budget: dict[str, Any] = field(default_factory=dict)
    changed_files: tuple[str, ...] = ()
    changed_sections: tuple[str, ...] = ()
    optimizer_worker_ref: str | None = None
    reasoning_summary: str | None = None
    patch_id: str | None = None
    target: SkillVersionRef | None = None
    rationale: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        patch_id = self.patch_id or self.candidate_id
        base_skill = self.base_skill or self.target
        reasoning = self.reasoning_summary or self.rationale
        if not str(patch_id or "").strip():
            raise HarnessValidationError("patch_id is required")
        if not isinstance(base_skill, SkillVersionRef):
            raise HarnessValidationError("base_skill must be SkillVersionRef")
        if not self.operations:
            raise HarnessValidationError("operations are required")
        operations = tuple(
            operation if isinstance(operation, SkillPatchOperation) else SkillPatchOperation.from_dict(operation)
            for operation in self.operations
        )
        forbidden = sorted(operation.op for operation in operations if operation.op in FORBIDDEN_SKILL_PATCH_OPERATIONS)
        if forbidden:
            raise HarnessValidationError("SkillPatchSet contains forbidden patch operations", details={"forbidden": forbidden})
        object.__setattr__(self, "patch_id", str(patch_id))
        object.__setattr__(self, "candidate_id", str(self.candidate_id or patch_id))
        object.__setattr__(self, "base_skill", base_skill)
        object.__setattr__(self, "target", base_skill)
        object.__setattr__(self, "operations", operations)
        object.__setattr__(self, "patch_budget", dict(self.patch_budget))
        object.__setattr__(self, "changed_files", tuple(str(item) for item in self.changed_files))
        object.__setattr__(self, "changed_sections", tuple(str(item) for item in self.changed_sections))
        object.__setattr__(self, "reasoning_summary", reasoning)
        object.__setattr__(self, "rationale", reasoning)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "candidate_id": self.candidate_id,
            "target": self.base_skill.to_dict() if self.base_skill else None,
            "base_skill": self.base_skill.to_dict() if self.base_skill else None,
            "operations": [operation.to_dict() for operation in self.operations],
            "patch_budget": to_jsonable(self.patch_budget),
            "changed_files": list(self.changed_files),
            "changed_sections": list(self.changed_sections),
            "optimizer_worker_ref": self.optimizer_worker_ref,
            "reasoning_summary": self.reasoning_summary,
            "rationale": self.rationale,
            "metadata": to_jsonable(self.metadata),
            "created_at": format_datetime(self.created_at),
        }


@dataclass(frozen=True)
class SkillStaticValidationResult:
    candidate_id: str
    passed: bool
    gate_results: tuple[dict[str, Any], ...]
    issues: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.candidate_id).strip():
            raise HarnessValidationError("candidate_id is required")
        object.__setattr__(self, "gate_results", tuple(dict(item) for item in self.gate_results))
        object.__setattr__(self, "issues", tuple(str(item) for item in self.issues))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "passed": self.passed,
            "gate_results": to_jsonable(list(self.gate_results)),
            "issues": list(self.issues),
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class SkillEvaluationCase:
    case_id: str
    split: SkillEvaluationSplit | str
    input_refs: tuple[str, ...]
    expected_refs: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.case_id).strip():
            raise HarnessValidationError("case_id is required")
        object.__setattr__(self, "split", SkillEvaluationSplit(self.split))
        object.__setattr__(self, "input_refs", tuple(str(ref) for ref in self.input_refs))
        object.__setattr__(self, "expected_refs", tuple(str(ref) for ref in self.expected_refs))
        object.__setattr__(self, "metrics", dict(self.metrics))

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "split": self.split.value,
            "input_refs": list(self.input_refs),
            "expected_refs": list(self.expected_refs),
            "metrics": to_jsonable(self.metrics),
        }


@dataclass(frozen=True)
class SkillEvaluationResult:
    candidate_id: str
    passed: bool
    score: float
    eval_case_count: int
    baseline_score: float | None = None
    held_out_score: float | None = None
    minimum_improvement: float = 0.0
    regression_tolerance: float = 0.0
    issues: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)
    case_results: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not str(self.candidate_id).strip():
            raise HarnessValidationError("candidate_id is required")
        for field_name in ("score", "baseline_score", "held_out_score", "minimum_improvement", "regression_tolerance"):
            value = getattr(self, field_name)
            if value is not None and not 0 <= value <= 1:
                raise HarnessValidationError(f"{field_name} must be between 0 and 1")
        if self.eval_case_count <= 0:
            raise HarnessValidationError("eval_case_count must be greater than zero")
        object.__setattr__(self, "issues", tuple(str(issue) for issue in self.issues))
        object.__setattr__(self, "metrics", dict(self.metrics))
        object.__setattr__(self, "case_results", tuple(dict(item) for item in self.case_results))

    @property
    def improvement(self) -> float | None:
        if self.baseline_score is None:
            return None
        return self.score - self.baseline_score

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "passed": self.passed,
            "score": self.score,
            "baseline_score": self.baseline_score,
            "held_out_score": self.held_out_score,
            "minimum_improvement": self.minimum_improvement,
            "regression_tolerance": self.regression_tolerance,
            "improvement": self.improvement,
            "eval_case_count": self.eval_case_count,
            "issues": list(self.issues),
            "metrics": to_jsonable(self.metrics),
            "case_results": to_jsonable(list(self.case_results)),
        }


@dataclass(frozen=True)
class SkillCandidate:
    candidate_id: str
    base_version: SkillVersionRef
    patch_set: SkillPatchSet
    candidate_version: str | None = None
    manifest_snapshot: dict[str, Any] = field(default_factory=dict)
    package_ref: str | None = None
    static_gate_results: tuple[dict[str, Any], ...] = ()
    evaluation_results: tuple[SkillEvaluationResult, ...] = ()
    promotion_decision: Any | None = None
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
        forbidden = sorted(FORBIDDEN_SKILL_CANDIDATE_KEYS.intersection(metadata))
        if forbidden:
            raise HarnessValidationError(
                "SkillCandidate must not contain publication bypass fields",
                details={"forbidden": forbidden},
            )
        object.__setattr__(self, "status", SkillCandidateStatus(self.status))
        object.__setattr__(self, "manifest_snapshot", dict(self.manifest_snapshot))
        object.__setattr__(self, "static_gate_results", tuple(dict(item) for item in self.static_gate_results))
        object.__setattr__(self, "evaluation_results", tuple(self.evaluation_results))
        object.__setattr__(self, "experiences", tuple(self.experiences))
        object.__setattr__(self, "metadata", metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "base_version": self.base_version.to_dict(),
            "candidate_version": self.candidate_version,
            "patch_set": self.patch_set.to_dict(),
            "manifest_snapshot": to_jsonable(self.manifest_snapshot),
            "package_ref": self.package_ref,
            "static_gate_results": to_jsonable(list(self.static_gate_results)),
            "evaluation_results": [result.to_dict() for result in self.evaluation_results],
            "promotion_decision": self.promotion_decision.to_dict() if hasattr(self.promotion_decision, "to_dict") else to_jsonable(self.promotion_decision),
            "experiences": [experience.to_dict() for experience in self.experiences],
            "status": self.status.value,
            "metadata": to_jsonable(self.metadata),
            "created_at": format_datetime(self.created_at),
        }


@dataclass(frozen=True)
class RejectedSkillCandidate:
    candidate: SkillCandidate
    reason: str
    gate_results: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    rejected_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, SkillCandidate):
            raise HarnessValidationError("candidate must be SkillCandidate")
        if not str(self.reason).strip():
            raise HarnessValidationError("rejected candidate reason is required")
        object.__setattr__(self, "gate_results", tuple(dict(item) for item in self.gate_results))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "reason": self.reason,
            "gate_results": to_jsonable(list(self.gate_results)),
            "metadata": to_jsonable(self.metadata),
            "rejected_at": format_datetime(self.rejected_at),
        }


@dataclass(frozen=True)
class SkillPromotionDecision:
    candidate_id: str
    status: SkillPromotionStatus | str
    decided_by: str = "harness"
    reasons: tuple[str, ...] = ()
    required_release_version: str | None = None
    gate_results: tuple[dict[str, Any], ...] = ()
    approval_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    decided_at: Any = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not str(self.candidate_id).strip():
            raise HarnessValidationError("candidate_id is required")
        if str(self.decided_by).strip() != "harness":
            raise HarnessValidationError("SkillPromotionDecision must be decided_by='harness'")
        object.__setattr__(self, "status", SkillPromotionStatus(self.status))
        object.__setattr__(self, "reasons", tuple(str(reason) for reason in self.reasons))
        object.__setattr__(self, "gate_results", tuple(dict(result) for result in self.gate_results))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def is_approved(self) -> bool:
        return self.status in {SkillPromotionStatus.PROMOTE, SkillPromotionStatus.APPROVED}

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "status": self.status.value,
            "decided_by": self.decided_by,
            "reasons": list(self.reasons),
            "required_release_version": self.required_release_version,
            "gate_results": to_jsonable(list(self.gate_results)),
            "approval_ref": self.approval_ref,
            "metadata": to_jsonable(self.metadata),
            "decided_at": format_datetime(self.decided_at),
        }


@dataclass(frozen=True)
class SkillRollbackPlan:
    release_id: str
    previous_version: SkillVersionRef | None
    triggers: tuple[str, ...]
    fallback_action: str = "halt_skill_use"
    rollback_transcript_ref: str | None = None
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
            "rollback_transcript_ref": self.rollback_transcript_ref,
            "metadata": to_jsonable(self.metadata),
        }


@dataclass(frozen=True)
class SkillRelease:
    release_id: str
    candidate_id: str
    version: SkillVersionRef
    rollback_plan: SkillRollbackPlan
    promotion_decision: SkillPromotionDecision | None = None
    release_notes_ref: str | None = None
    transcript_refs: tuple[str, ...] = ()
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
        object.__setattr__(self, "transcript_refs", tuple(str(ref) for ref in self.transcript_refs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "candidate_id": self.candidate_id,
            "version": self.version.to_dict(),
            "rollback_plan": self.rollback_plan.to_dict(),
            "promotion_decision": self.promotion_decision.to_dict() if self.promotion_decision else None,
            "release_notes_ref": self.release_notes_ref,
            "transcript_refs": list(self.transcript_refs),
            "metadata": to_jsonable(self.metadata),
            "released_at": format_datetime(self.released_at),
        }


def ensure_jsonable_skill_model(value: Any) -> None:
    stable_json_dumps(to_jsonable(value))


__all__ = [
    "ALLOWED_SKILL_PATCH_OPERATIONS",
    "FORBIDDEN_SKILL_CANDIDATE_KEYS",
    "FORBIDDEN_SKILL_PATCH_OPERATIONS",
    "RejectedSkillCandidate",
    "SkillCandidate",
    "SkillCandidateStatus",
    "SkillEvaluationCase",
    "SkillEvaluationResult",
    "SkillEvaluationSplit",
    "SkillEvolutionBudget",
    "SkillEvolutionRunSpec",
    "SkillEvolutionState",
    "SkillEvolutionStatus",
    "SkillExperience",
    "SkillExperienceOutcome",
    "SkillExperiencePool",
    "SkillPatchOperation",
    "SkillPatchSet",
    "SkillPromotionDecision",
    "SkillPromotionStatus",
    "SkillRelease",
    "SkillRollbackPlan",
    "SkillStaticValidationResult",
    "SkillVersionRef",
    "ensure_jsonable_skill_model",
]
