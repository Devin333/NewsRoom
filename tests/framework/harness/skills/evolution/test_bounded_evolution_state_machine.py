from __future__ import annotations

from framework.harness import FakeSkillEvolutionPort, SkillPromotionStatus


def test_fake_skill_evolution_lifecycle_does_not_publish_before_harness_decision() -> None:
    evolution = FakeSkillEvolutionPort()
    evolution.collect_experience({"skill_name": "reader.repair", "summary": "Successful repair preserved lineage.", "outcome": "success"})
    evolution.collect_experience({"skill_name": "reader.repair", "summary": "Failed repair lost table refs.", "outcome": "failure"})
    candidate = evolution.propose_candidate({"skill_name": "reader.repair"})

    assert evolution.active_versions == {}

    evaluation = evolution.evaluate_candidate(candidate)
    decision = evolution.decide_promotion(evaluation)

    assert decision.status == SkillPromotionStatus.APPROVED
    assert evolution.active_versions == {}

    release = evolution.promote_candidate(decision)
    assert evolution.active_versions["reader.repair"].version == "0.2.0"
    assert release.rollback_plan.previous_version.version == "0.1.0"


def test_fake_skill_evolution_records_rejected_candidate_without_release() -> None:
    evolution = FakeSkillEvolutionPort()
    candidate = evolution.propose_candidate(
        {
            "skill_name": "reader.repair",
            "metadata": {"baseline_score": 0.8, "candidate_score": 0.8, "minimum_improvement": 0.05},
        }
    )
    evaluation = evolution.evaluate_candidate(candidate)
    decision = evolution.decide_promotion(evaluation)

    assert decision.status.value == "reject"
    assert evolution.active_versions == {}
