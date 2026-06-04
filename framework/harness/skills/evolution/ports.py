from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from framework.harness.skills.evolution.models import (
    SkillCandidate,
    SkillEvaluationResult,
    SkillExperiencePool,
    SkillExperience,
    SkillPatchSet,
    SkillPromotionDecision,
    SkillRelease,
    SkillRollbackPlan,
)


@runtime_checkable
class SkillEvolutionPort(Protocol):
    def collect_experience(self, request: dict) -> SkillExperience:
        ...

    def propose_candidate(self, request: dict) -> SkillCandidate:
        ...

    def evaluate_candidate(self, candidate: SkillCandidate) -> SkillEvaluationResult:
        ...

    def promote_candidate(self, decision: SkillPromotionDecision) -> SkillRelease:
        ...

    def rollback_release(self, release: SkillRelease) -> SkillRollbackPlan:
        ...


@runtime_checkable
class SkillExperienceStorePort(Protocol):
    def append_experience(self, experience: SkillExperience) -> SkillExperience:
        ...

    def query_experiences(self, request: dict[str, Any]) -> tuple[SkillExperience, ...]:
        ...

    def build_pool(self, request: dict[str, Any]) -> SkillExperiencePool:
        ...


@runtime_checkable
class SkillCandidateStorePort(Protocol):
    def save_candidate(self, candidate: SkillCandidate) -> SkillCandidate:
        ...

    def get_candidate(self, candidate_id: str) -> SkillCandidate:
        ...

    def list_candidates(self, request: dict[str, Any] | None = None) -> tuple[SkillCandidate, ...]:
        ...

    def save_rejected(self, candidate: SkillCandidate, reason: str) -> SkillCandidate:
        ...

    def list_rejected(self, request: dict[str, Any] | None = None) -> tuple[SkillCandidate, ...]:
        ...


@runtime_checkable
class SkillOptimizerWorkerPort(Protocol):
    def propose_patch(self, request: dict[str, Any]) -> SkillPatchSet:
        ...


@runtime_checkable
class SkillEvaluationPort(Protocol):
    def run_static_validation(self, candidate: SkillCandidate) -> dict[str, Any]:
        ...

    def run_eval_suite(self, candidate: SkillCandidate, eval_request: dict[str, Any]) -> SkillEvaluationResult:
        ...

    def run_sandbox_trial(self, candidate: SkillCandidate, sandbox_request: dict[str, Any]) -> SkillEvaluationResult:
        ...


@runtime_checkable
class SkillPromotionPort(Protocol):
    def prepare_release(self, candidate: SkillCandidate, decision: SkillPromotionDecision) -> SkillRelease:
        ...

    def publish_release(self, release: SkillRelease) -> SkillRelease:
        ...

    def rollback(self, rollback_plan: SkillRollbackPlan) -> SkillRollbackPlan:
        ...

    def get_active_version(self, skill_name: str) -> object:
        ...


__all__ = [
    "SkillCandidateStorePort",
    "SkillEvaluationPort",
    "SkillEvolutionPort",
    "SkillExperienceStorePort",
    "SkillOptimizerWorkerPort",
    "SkillPromotionPort",
]
