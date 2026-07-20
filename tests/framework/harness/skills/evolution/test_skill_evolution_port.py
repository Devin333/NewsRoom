from __future__ import annotations

import pytest

from framework.harness import FakeSkillEvolutionPort, HarnessValidationError, SkillPromotionDecision


def test_skill_candidate_does_not_auto_replace_active_skill() -> None:
    evolution = FakeSkillEvolutionPort()
    evolution.collect_experience({"summary": "Reader repair should preserve evidence refs."})
    candidate = evolution.propose_candidate({"skill_id": "reader.repair"})
    evaluation = evolution.evaluate_candidate(candidate)

    assert evaluation.passed is True
    assert evolution.active_versions == {}


def test_skill_promotion_requires_harness_decision() -> None:
    evolution = FakeSkillEvolutionPort()
    candidate = evolution.propose_candidate({"skill_id": "reader.repair"})
    evaluation = evolution.evaluate_candidate(candidate)
    decision = evolution.decide_promotion(evaluation)
    release = evolution.promote_candidate(decision)

    assert release.candidate_id == candidate.candidate_id
    assert evolution.active_versions["reader.repair"].version == "0.2.0"
    rollback = evolution.rollback_release(release)
    assert rollback.metadata["rolled_back"] is True
    assert evolution.active_versions["reader.repair"].version == "0.1.0"


def test_rejected_skill_promotion_decision_cannot_release() -> None:
    evolution = FakeSkillEvolutionPort()
    candidate = evolution.propose_candidate({"skill_id": "reader.repair"})
    decision = SkillPromotionDecision(candidate_id=candidate.candidate_id, status="rejected")

    with pytest.raises(HarnessValidationError):
        evolution.promote_candidate(decision)


def test_caller_created_approved_decision_cannot_release() -> None:
    evolution = FakeSkillEvolutionPort()
    candidate = evolution.propose_candidate({"skill_id": "reader.repair"})
    decision = SkillPromotionDecision(candidate_id=candidate.candidate_id, status="approved")

    with pytest.raises(HarnessValidationError):
        evolution.promote_candidate(decision)

    assert evolution.releases == {}
    assert evolution.release_registry.version_history == {}
    assert evolution.active_versions == {}
