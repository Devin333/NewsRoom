from __future__ import annotations

from framework.harness import SkillEvalReplayRunner, SkillEvaluationResult, SkillPromotionDecider, SkillPromotionStatus
from tests.framework.harness.skills.evolution.test_static_gates import _candidate


def test_promotion_gate_approves_candidate_after_static_and_eval_success() -> None:
    candidate = _candidate()
    evaluation = SkillEvalReplayRunner().run_eval_suite(
        candidate,
        {
            "baseline_score": 0.7,
            "candidate_score": 0.86,
            "minimum_improvement": 0.05,
            "metrics": {"evidence_coverage": 0.92},
        },
    )

    decision = SkillPromotionDecider().decide(candidate, evaluation, release_version="1.1.0")

    assert decision.status == SkillPromotionStatus.PROMOTE
    assert decision.required_release_version == "1.1.0"
    assert decision.decided_by == "harness"


def test_promotion_gate_requires_approval_for_high_risk_tools() -> None:
    candidate = _candidate(allowed_tools=("llm", "shell"))
    evaluation = SkillEvalReplayRunner().run_eval_suite(
        candidate,
        {
            "baseline_score": 0.7,
            "candidate_score": 0.86,
            "minimum_improvement": 0.05,
        },
    )

    decision = SkillPromotionDecider().decide(candidate, evaluation)

    assert decision.status == SkillPromotionStatus.NEEDS_HUMAN_APPROVAL


def test_promotion_gate_rejects_evaluation_without_held_out_evidence() -> None:
    candidate = _candidate()
    evaluation = SkillEvaluationResult(
        candidate_id=candidate.candidate_id,
        passed=True,
        score=0.9,
        baseline_score=0.7,
        held_out_score=None,
        eval_case_count=1,
        case_results=(),
    )

    decision = SkillPromotionDecider().decide(candidate, evaluation)

    assert decision.status == SkillPromotionStatus.REJECT
    assert any("evaluation_unavailable" in reason for reason in decision.reasons)
