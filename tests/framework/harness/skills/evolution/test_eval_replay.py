from __future__ import annotations

from framework.harness import SkillEvalReplayRunner, SkillPromotionDecider
from tests.framework.harness.skills.evolution.test_static_gates import _candidate


def test_eval_replay_requires_strict_held_out_improvement() -> None:
    candidate = _candidate()

    evaluation = SkillEvalReplayRunner().run_eval_suite(
        candidate,
        {
            "baseline_score": 0.8,
            "candidate_score": 0.81,
            "minimum_improvement": 0.05,
            "max_eval_cases": 2,
        },
    )

    decision = SkillPromotionDecider().decide(candidate, evaluation)

    assert evaluation.passed is False
    assert decision.status.value == "reject"


def test_eval_replay_rejects_critical_metric_regression_even_with_higher_score() -> None:
    candidate = _candidate()

    evaluation = SkillEvalReplayRunner().run_eval_suite(
        candidate,
        {
            "baseline_score": 0.7,
            "candidate_score": 0.9,
            "minimum_improvement": 0.05,
            "metrics": {"evidence_coverage_regressed": True},
        },
    )
    decision = SkillPromotionDecider().decide(candidate, evaluation)

    assert evaluation.passed is False
    assert decision.status.value == "reject"
