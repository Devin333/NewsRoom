from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.skills.evolution.gates import SkillPromotionGate
from framework.harness.skills.evolution.models import (
    SkillCandidate,
    SkillEvaluationResult,
    SkillPromotionDecision,
    SkillPromotionStatus,
)


class SkillPromotionDecider:
    def __init__(self, gate: SkillPromotionGate | None = None) -> None:
        self.gate = gate or SkillPromotionGate()

    def decide(
        self,
        candidate: SkillCandidate,
        evaluation: SkillEvaluationResult,
        *,
        approval_ref: str | None = None,
        release_version: str | None = None,
    ) -> SkillPromotionDecision:
        result = self.gate.evaluate(candidate, evaluation, approval_ref=approval_ref)
        if result.passed:
            return SkillPromotionDecision(
                candidate_id=candidate.candidate_id,
                status=SkillPromotionStatus.PROMOTE,
                reasons=("static gates and held-out eval passed",),
                required_release_version=release_version or candidate.candidate_version,
                gate_results=(result.to_dict(),),
                approval_ref=approval_ref,
            )
        needs_approval = any(
            item.get("gate") == "skill_allowed_tools" and item.get("passed") is False
            for item in result.details.get("gate_results", ())
        )
        status = SkillPromotionStatus.NEEDS_HUMAN_APPROVAL if needs_approval else SkillPromotionStatus.REJECT
        return SkillPromotionDecision(
            candidate_id=candidate.candidate_id,
            status=status,
            reasons=(result.reason or "candidate failed promotion gate",),
            gate_results=(result.to_dict(),),
            approval_ref=approval_ref,
        )

    def require_harness_decision(self, decision: SkillPromotionDecision) -> SkillPromotionDecision:
        if decision.decided_by != "harness":
            raise HarnessValidationError("promotion decision must be Harness-owned")
        return decision


def attach_promotion_decision(candidate: SkillCandidate, decision: SkillPromotionDecision) -> SkillCandidate:
    return replace(candidate, promotion_decision=decision)


__all__ = ["SkillPromotionDecider", "attach_promotion_decision"]
