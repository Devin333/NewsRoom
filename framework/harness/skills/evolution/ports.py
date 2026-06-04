from __future__ import annotations

from typing import Protocol, runtime_checkable

from framework.harness.skills.evolution.models import (
    SkillCandidate,
    SkillEvaluationResult,
    SkillExperience,
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


__all__ = ["SkillEvolutionPort"]
